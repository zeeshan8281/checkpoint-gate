import test from "node:test";
import assert from "node:assert/strict";
import { lease, assertLease, validateName } from "../src/state.js";

test("lease renewal requires same owner AND fencing token", () => {
  const state = { lease: lease({}, { owner: "one" }, 100, 500) };
  assert.equal(lease(state, { owner: "one", fence: 1 }, 200, 500).fence, 1);
  assert.throws(() => lease(state, { owner: "two" }, 200, 500));
  assert.throws(() => lease(state, { owner: "one" }, 200, 500));
  assertLease(state, { owner: "one", fence: 1 }, 200);
});

test("expiry fences old worker and forbids automatic renewal", () => {
  const state = { lease: { owner: "one", fence: 3, expires: 200 } };
  assert.throws(() => assertLease(state, { owner: "one", fence: 3 }, 200));
  assert.throws(() => lease(state, { owner: "one", fence: 3 }, 201, 500));
  const next = lease(state, { owner: "two" }, 201, 500);
  assert.equal(next.fence, 4);
  assert.throws(() => assertLease({ lease: next }, { owner: "one", fence: 3 }, 202));
});

test("receipt names cannot become arbitrary object paths", () => {
  validateName("checkpoint-sft");
  assert.throws(() => validateName("../secret"));
  assert.throws(() => validateName(""));
});
