// Run against `wrangler dev --local` with a local CONTROL_TOKEN.
import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";

const base = process.env.TEST_WORKER_URL || "http://127.0.0.1:8787";
const token = process.env.CHECKPOINT_GATE_TOKEN;
assert.ok(token, "Set CHECKPOINT_GATE_TOKEN to the local Worker CONTROL_TOKEN");
const campaign = `integration-${randomUUID()}`;
async function call(action, body, auth = true) {
  const response = await fetch(`${base}/api/campaigns/${campaign}/${action}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", ...(auth ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  return { status: response.status, body: await response.json() };
}
assert.equal((await call("status", undefined, false)).status, 401);
assert.equal((await call("init", { manifest: { test: true } })).status, 200);
assert.equal((await call("init", { manifest: { test: false } })).status, 409);
const first = await call("lease", { owner: "one" });
assert.equal(first.status, 200);
assert.equal((await call("lease", { owner: "two" })).status, 409);
const data = '{"actual_local_integration_test":true}';
const receipt = {
  owner: "one", fence: first.body.fence, name: "result", data,
  sha256: createHash("sha256").update(data).digest("hex")
};
assert.equal((await call("receipt", { ...receipt, fence: 999 })).status, 409);
assert.equal((await call("receipt", { ...receipt, sha256: "a".repeat(64) })).status, 409);
assert.equal((await call("receipt", receipt)).status, 200);
assert.equal((await call("receipt", receipt)).body.duplicate, true);
const changed = '{"changed":true}';
assert.equal((await call("receipt", {
  ...receipt, data: changed, sha256: createHash("sha256").update(changed).digest("hex")
})).status, 409);
const status = await call("status");
assert.equal(status.body.receipts["receipt:result"].sha256, receipt.sha256);
console.log(JSON.stringify({ passed: 10, runtime: "local workerd, SQLite Durable Object and R2",
                             campaign, sha256: receipt.sha256 }, null, 2));
