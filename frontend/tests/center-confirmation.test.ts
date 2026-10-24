import { expect, it } from "vitest";
import { initialCenter, observe, updateCenter } from "../src/model";
import { clientState } from "./fixtures";
it("keeps same-ID placement but reconfirms each term or instance using distinct snapshots", () => {
  const state = clientState();
  let center = updateCenter(initialCenter(), observe(state, 1_000_000), "s", 1);
  center = updateCenter(center, observe(state, 1_000_000), "s", 2);
  expect(center.confirmed).toBe(1);
  for (const [seq, change] of [
    [3, () => state.frame!.snapshot.nodes![0].status!.term++],
    [
      5,
      () => {
        state.frame!.snapshot.nodes![0].status!.instance_id = "restarted";
      },
    ],
  ] as const) {
    change();
    const observation = observe(state, 1_000_000);
    center = updateCenter(center, observation, "s", seq);
    expect(center.display).toBe(1);
    expect(center.confirmed).toBeNull();
    center = updateCenter(center, observation, "s", seq);
    expect(center.confirmed).toBeNull();
    center = updateCenter(center, observation, "s", seq + 1);
    expect(center.confirmed).toBe(1);
  }
});
