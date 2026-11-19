export class Conflict extends Error {}

export function lease(state, input, now, ttl) {
  if (!state) throw new Conflict("Initialize campaign first");
  if (!/^[a-zA-Z0-9_-]{1,80}$/.test(input.owner || "")) throw new Conflict("Invalid owner");
  const old = state.lease;
  if (old && old.expires > now) {
    if (old.owner !== input.owner || input.fence !== old.fence)
      throw new Conflict("Campaign is already leased");
    return { ...old, expires: now + ttl };
  }
  // Expiry permits only evidence ownership. It never schedules a paid operation.
  if (input.fence !== undefined) throw new Conflict("Expired lease; automatic takeover forbidden");
  return { owner: input.owner, fence: (old?.fence || 0) + 1, expires: now + ttl };
}

export function assertLease(state, input, now) {
  const l = state?.lease;
  if (!l || l.owner !== input.owner || l.fence !== input.fence || l.expires <= now)
    throw new Conflict("Missing, expired, or fenced lease");
}

export function validateName(name) {
  if (!/^[a-zA-Z0-9_-]{1,100}$/.test(name || "")) throw new Conflict("Invalid receipt name");
}
