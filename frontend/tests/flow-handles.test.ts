import { expect, it } from "vitest";
import {
  adoptUserNodes,
  Position,
  type NodeBase,
  type NodeLookup,
  type ParentLookup,
} from "@xyflow/system";

for (const explicit of [false, true]) {
  it(`${explicit ? "fixed" : "DOM-only"} handles across an immutable status update`, () => {
    const handles = [
      {
        type: "source" as const,
        position: Position.Top,
        x: 37,
        y: -3,
        width: 6,
        height: 6,
      },
      {
        type: "target" as const,
        position: Position.Bottom,
        x: 37,
        y: 77,
        width: 6,
        height: 6,
      },
    ];
    const node: NodeBase = {
      id: "1",
      position: { x: 0, y: 0 },
      width: 80,
      height: 80,
      data: { revision: 1 },
      ...(explicit ? { handles } : {}),
    };
    const lookup: NodeLookup = new Map(),
      parents: ParentLookup = new Map();
    adoptUserNodes([node], lookup, parents);
    // Simulate the initial DOM measurement, then the next immutable node data.
    const initial = lookup.get("1")!;
    initial.measured = { width: 80, height: 80 };
    initial.internals.handleBounds = {
      source: [{ ...handles[0], nodeId: "1" }],
      target: [{ ...handles[1], nodeId: "1" }],
    };
    adoptUserNodes([{ ...node, data: { revision: 2 } }], lookup, parents);
    expect(Boolean(lookup.get("1")!.internals.handleBounds)).toBe(explicit);
  });
}
