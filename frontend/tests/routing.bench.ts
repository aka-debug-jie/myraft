import { bench, describe } from "vitest";
import { layoutNodes, routeEdges } from "../src/geometry";
import { observe } from "../src/model";
import { clientState } from "./fixtures";

for (const [width, height] of [
  [1200, 900],
  [400, 600],
  [390, 250],
]) {
  const state = clientState(Array.from({ length: 100 }, (_, i) => i + 1));
  state.frame!.snapshot.nodes![1].status!.state = "Leader";
  const observed = observe(state, 1_000_000);
  const layout = layoutNodes(observed.nodes, null, width, height);
  describe(`100 nodes / 2 observed Leaders / ${width}x${height}`, () => {
    bench("route all 98 reported relationships", () => {
      if (routeEdges(layout, observed.relations).length !== 98)
        throw new Error("a relationship was omitted");
    });
  });
}
