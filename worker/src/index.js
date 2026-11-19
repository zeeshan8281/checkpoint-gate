import { DurableObject } from "cloudflare:workers";
import { Conflict, lease, assertLease, validateName } from "./state.js";

const json = (data, status = 200) => Response.json(data, {
  status, headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" }
});
const hex = b => Array.from(new Uint8Array(b), x => x.toString(16).padStart(2, "0")).join("");
const sha256 = async text => hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));

async function authorized(request, env) {
  if (!env.CONTROL_TOKEN || env.CONTROL_TOKEN.length < 24) return false;
  const given = request.headers.get("Authorization") || "";
  if (given.length > 1024) return false;
  const a = await sha256(given), b = await sha256(`Bearer ${env.CONTROL_TOKEN}`);
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return difference === 0;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    if (!await authorized(request, env)) return json({ error: "unauthorized" }, 401);
    const match = url.pathname.match(/^\/api\/campaigns\/([a-zA-Z0-9_-]{1,80})\/(init|lease|receipt|status)$/);
    if (!match) return json({ error: "not_found" }, 404);
    const id = env.CAMPAIGNS.idFromName(match[1]);
    return env.CAMPAIGNS.get(id).fetch(request);
  }
};

export class Campaign extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.ctx = ctx;
    this.env = env;
  }

  async fetch(request) {
    const action = new URL(request.url).pathname.split("/").pop();
    if (action === "status" && request.method === "GET") {
      const state = await this.ctx.storage.get("state");
      const receipts = await this.ctx.storage.list({ prefix: "receipt:" });
      return json({ state: state || null, receipts: Object.fromEntries(receipts) });
    }
    if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
    // Stream-bound request body; Content-Length is not trusted.
    const reader = request.body?.getReader();
    if (!reader) return json({ error: "missing_body" }, 400);
    let length = 0;
    const chunks = [];
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > 2_000_000) { await reader.cancel(); return json({ error: "body_too_large" }, 413); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    try {
      const input = JSON.parse(new TextDecoder().decode(bytes));
      if (action === "init") {
        const serialized = JSON.stringify(input.manifest);
        if (!input.manifest || serialized.length > 32_000) throw new Conflict("Invalid manifest");
        const hash = await sha256(serialized);
        return await this.ctx.storage.transaction(async txn => {
          const old = await txn.get("state");
          if (old && old.manifestHash !== hash) throw new Conflict("Manifest is immutable");
          if (!old) await txn.put("state", { manifest: input.manifest, manifestHash: hash, created: Date.now() });
          return json({ initialized: true, manifestHash: hash });
        });
      }
      if (action === "lease") {
        return await this.ctx.storage.transaction(async txn => {
          const state = await txn.get("state");
          const seconds = Math.max(2, Math.min(600, Number(this.env.LEASE_SECONDS) || 600));
          const next = lease(state, input, Date.now(), seconds * 1000);
          await txn.put("state", { ...state, lease: next });
          return json(next);
        });
      }
      if (action === "receipt") {
        validateName(input.name);
        if (typeof input.data !== "string" || !/^[0-9a-f]{64}$/.test(input.sha256 || ""))
          throw new Conflict("Invalid evidence");
        if (await sha256(input.data) !== input.sha256) throw new Conflict("Evidence digest mismatch");
        assertLease(await this.ctx.storage.get("state"), input, Date.now());
        // Content addressing makes repeated uploads safe. A failed commit may leave an orphan.
        const key = `sha256/${input.sha256}.json`;
        await this.env.EVIDENCE.put(key, input.data, { httpMetadata: { contentType: "application/json" } });
        return await this.ctx.storage.transaction(async txn => {
          assertLease(await txn.get("state"), input, Date.now());
          const old = await txn.get(`receipt:${input.name}`);
          if (old && old.sha256 !== input.sha256) throw new Conflict("Receipt identity is immutable");
          const receipt = old || { key, sha256: input.sha256, bytes: input.data.length, created: Date.now() };
          await txn.put(`receipt:${input.name}`, receipt);
          return json({ ...receipt, duplicate: Boolean(old) });
        });
      }
      return json({ error: "not_found" }, 404);
    } catch (error) {
      if (error instanceof Conflict) return json({ error: error.message }, 409);
      if (error instanceof SyntaxError) return json({ error: "invalid_json" }, 400);
      return json({ error: "storage_error" }, 500);
    }
  }
}
