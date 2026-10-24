import { expect, it } from "vitest";
import { mergeReceipts } from "../src/receipts";
import { clientState } from "./fixtures";
it("shows HTTP receipt once, lets SSE replace it, and never resurrects an evicted receipt", () => {
  const state = clientState();
  state.receipt = {
    id: "a",
    session_id: "session-a",
    generation: 1,
    kind: "generate",
    state: "queued",
    created_at: "",
    accepted: null,
    committed: null,
  };
  let view = mergeReceipts(null, state);
  expect(view.operations.map((o) => o.state)).toEqual(["queued"]);
  state.frame!.operations = [
    { ...state.receipt, state: "succeeded", committed: true },
  ];
  view = mergeReceipts(view, state);
  expect(view.operations.map((o) => o.state)).toEqual(["succeeded"]);
  state.frame!.operations = [];
  view = mergeReceipts(view, state);
  expect(view.operations).toHaveLength(0);
  state.frame!.generation = 2;
  expect(mergeReceipts(view, state).operations).toHaveLength(0);
});
