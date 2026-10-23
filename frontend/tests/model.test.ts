import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../src/api";
import { ConsoleClient } from "../src/client";
import {
  layoutNodes,
  nearestEdge,
  routeEdges,
  segmentDistance,
  type RoutedEdge,
} from "../src/geometry";
import { initialCenter, observe, updateCenter } from "../src/model";
import {
  bootstrap as bootstrapFixture,
  clientState,
  frame,
  sample,
} from "./fixtures";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("observation model", () => {
  it("reports 99 same-term follower relations for an 11 or 100 member cluster", () => {
    for (const count of [11, 100]) {
      const ids = Array.from({ length: count }, (_, i) => i + 1);
      const observedFrame = frame(ids);
      observedFrame.snapshot.nodes = ids.map((id) =>
        id === 1
          ? sample(id, {
              status: {
                ...sample(id).status!,
                state: "Leader",
                term: 9,
                leader_id: id,
              },
            })
          : sample(id, {
              status: {
                ...sample(id).status!,
                state: "Follower",
                term: 9,
                leader_id: 1,
              },
            }),
      );
      const result = observe(
        clientState(ids, { frame: observedFrame }),
        1_000_000,
      );
      expect(result.relations).toHaveLength(count - 1);
      expect(
        result.relations.every(
          (relation) => relation.term === 9 && relation.to === 1,
        ),
      ).toBe(true);
    }
  });

  it("classifies an offline sample as offline even when identity_ok is false", () => {
    const observedFrame = frame();
    observedFrame.snapshot.nodes = [
      sample(1),
      sample(2, { reachable: false, identity_ok: false }),
    ];
    const result = observe(
      clientState([1, 2, 3], { frame: observedFrame }),
      1_000_000,
    );
    expect(result.nodes.find((node) => node.id === 2)?.availability).toBe(
      "offline",
    );
  });

  it("does not confirm on duplicate sequence, confirms on the second sequence, and returns an old leader to its ID slot", () => {
    const state = clientState();
    const first = observe(state, 1_000_000);
    const one = updateCenter(initialCenter(), first, "scope-a", 4);
    expect(one.confirmed).toBeNull();
    expect(updateCenter(one, first, "scope-a", 4).confirmed).toBeNull();
    const two = updateCenter(one, first, "scope-a", 5);
    expect(two.confirmed).toBe(1);
    const nextFrame = frame();
    nextFrame.snapshot.nodes![0].status!.state = "Follower";
    nextFrame.snapshot.nodes![0].status!.leader_id = 2;
    nextFrame.snapshot.nodes![1].status!.state = "Leader";
    nextFrame.snapshot.nodes![1].status!.leader_id = 2;
    const next = observe(
      clientState(undefined, { frame: nextFrame }),
      1_000_000,
    );
    const pending = updateCenter(two, next, "scope-a", 6);
    expect(pending.display).toBeNull();
    expect(updateCenter(pending, next, "scope-a", 6).display).toBeNull();
    expect(updateCenter(pending, next, "scope-a", 7).display).toBe(2);

    const nodes = first.nodes;
    const oldLeaderSlot = layoutNodes(nodes, 1, 1200, 900).slots.get(1)!;
    const moved = layoutNodes(nodes, 2, 1200, 900);
    expect(moved.nodes.find((node) => node.id === 1)).toMatchObject(
      oldLeaderSlot,
    );
    expect(
      layoutNodes(nodes, 1, 1200, 900).nodes.find((node) => node.id === 1)?.x,
    ).toBe(600);
  });
});

describe("topology geometry", () => {
  it("lays out every member without node overlap at all supported cluster sizes", () => {
    for (const count of [3, 11, 20, 50, 100]) {
      const ids = Array.from({ length: count }, (_, i) => i + 1);
      const nodes = observe(clientState(ids), 1_000_000).nodes;
      const layout = layoutNodes(nodes, 1, 1200, 900);
      expect(layout.nodes).toHaveLength(count);
      expect(new Set(layout.nodes.map((node) => node.id))).toEqual(
        new Set(ids),
      );
      for (let i = 0; i < layout.nodes.length; i++)
        for (let j = i + 1; j < layout.nodes.length; j++) {
          const a = layout.nodes[i],
            b = layout.nodes[j];
          expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(
            a.r + b.r,
          );
        }
    }
  });

  it("routes ordinary single-leader spokes without crossing other nodes", () => {
    const observation = observe(clientState(), 1_000_000);
    const layout = layoutNodes(observation.nodes, 1, 1200, 900);
    const edges = routeEdges(layout, observation.relations);
    expect(edges).toHaveLength(observation.relations.length);
    for (const edge of edges) {
      const obstacles = layout.nodes.filter(
        (node) => node.id !== edge.from && node.id !== edge.to,
      );
      for (let i = 1; i < edge.points.length; i++)
        for (const obstacle of obstacles) {
          expect(
            segmentDistance(edge.points[i - 1], edge.points[i], obstacle),
          ).toBeGreaterThan(obstacle.r + 3);
        }
    }
  });

  it("returns the edge with the smallest distance to the pointer", () => {
    const edge = (id: string, y: number): RoutedEdge => ({
      id,
      from: 1,
      to: 2,
      term: 1,
      points: [
        { x: 0, y },
        { x: 10, y },
      ],
      path: `M0,${y} L10,${y}`,
    });
    expect(
      nearestEdge([edge("far", 4), edge("near", 1)], { x: 5, y: 1.2 }, 5),
    ).toBe("near");
    expect(nearestEdge([edge("near", 1)], { x: 5, y: 9 }, 5)).toBeNull();
  });
});

describe("console client write and lifecycle boundaries", () => {
  beforeEach(() => {
    vi.spyOn(Date, "now").mockReturnValue(1_000_000);
  });
  it("rejects a second synchronous click while pending, sending only one operation", async () => {
    const client = new ConsoleClient();
    vi.spyOn(api, "bootstrap").mockResolvedValue(bootstrapFixture());
    client.receive(frame());
    await vi.waitFor(() =>
      expect(client.getSnapshot().bootstrap).not.toBeNull(),
    );
    let resolveOperation!: (
      value: Awaited<ReturnType<typeof api.operate>>,
    ) => void;
    const operation = new Promise<Awaited<ReturnType<typeof api.operate>>>(
      (resolve) => {
        resolveOperation = resolve;
      },
    );
    const operate = vi.spyOn(api, "operate").mockReturnValue(operation);
    const first = client.execute("generate", { count: 1, seed: 42 });
    await expect(
      client.execute("generate", { count: 1, seed: 42 }),
    ).rejects.toThrow("请求已发出");
    expect(operate).toHaveBeenCalledTimes(1);
    resolveOperation({
      id: "op-a",
      session_id: "session-a",
      generation: 1,
      kind: "generate",
      state: "queued",
      created_at: "",
      accepted: null,
      committed: null,
    });
    await first;
    expect(client.getSnapshot().receipt?.id).toBe("op-a");
  });

  it("marks a dropped write result unknown and does not automatically resend it", async () => {
    const client = new ConsoleClient();
    vi.spyOn(api, "bootstrap").mockResolvedValue(bootstrapFixture());
    client.receive(frame());
    await vi.waitFor(() =>
      expect(client.getSnapshot().bootstrap).not.toBeNull(),
    );
    const operate = vi
      .spyOn(api, "operate")
      .mockRejectedValue(new TypeError("connection dropped"));
    await expect(
      client.execute("generate", { count: 1, seed: 42 }),
    ).rejects.toThrow("connection dropped");
    expect(operate).toHaveBeenCalledTimes(1);
    expect(client.getSnapshot().unknownWrite).toBe(true);
  });

  it("does not apply a receipt after the active scope changes", async () => {
    const client = new ConsoleClient();
    vi.spyOn(api, "bootstrap").mockResolvedValue(bootstrapFixture());
    client.receive(frame());
    await vi.waitFor(() =>
      expect(client.getSnapshot().bootstrap).not.toBeNull(),
    );
    let resolveOperation!: (
      value: Awaited<ReturnType<typeof api.operate>>,
    ) => void;
    const operation = new Promise<Awaited<ReturnType<typeof api.operate>>>(
      (resolve) => {
        resolveOperation = resolve;
      },
    );
    vi.spyOn(api, "operate").mockReturnValue(operation);
    const submitted = client.execute("generate", { count: 1, seed: 42 });
    client.receive(frame([1, 2, 3], { generation: 2 }));
    resolveOperation({
      id: "stale-op",
      session_id: "session-a",
      generation: 1,
      kind: "generate",
      state: "queued",
      created_at: "",
      accepted: null,
      committed: null,
    });
    await submitted;
    expect(client.getSnapshot().receipt).toBeNull();
  });

  it("closes its EventSource when the application subscription is disposed", async () => {
    vi.spyOn(api, "bootstrap").mockResolvedValue(bootstrapFixture());
    let created: { close: ReturnType<typeof vi.fn> } | undefined;
    class EventSourceStub {
      close = vi.fn();
      onerror: ((event: Event) => void) | null = null;
      addEventListener() {}
      constructor() {
        created = this;
      }
    }
    vi.stubGlobal("EventSource", EventSourceStub);
    const client = new ConsoleClient();
    const stop = client.start();
    await vi.waitFor(() => expect(created).toBeDefined());
    stop();
    expect(created!.close).toHaveBeenCalledTimes(1);
  });
});
