import { describe, expect, it } from "vitest";
import { deriveSummary, updateRate } from "../src/summary";
import { clientState, frame, sample } from "./fixtures";

describe("updateRate", () => {
  it("resets decreases, identical timestamps and gaps; render clock may lag a new frame", () => {
    const state = clientState();
    state.frame!.snapshot.monitor_rpcs = 100;
    const base = updateRate(null, state, 1_000_000)!;
    const next = structuredClone(state);
    next.frame!.snapshot.seq = 2;
    next.frame!.snapshot.completed_at = new Date(1_001_000).toISOString();
    next.frame!.snapshot.monitor_rpcs = 111;
    expect(updateRate(base, next, 1_000_999)?.value).toBe(11);
    next.frame!.snapshot.monitor_rpcs = 99;
    expect(updateRate(base, next, 1_001_000)?.value).toBeNull();
    next.frame!.snapshot.monitor_rpcs = 111;
    next.frame!.snapshot.completed_at = state.frame!.snapshot.completed_at;
    expect(updateRate(base, next, 1_001_000)?.value).toBeNull();
    next.frame!.snapshot.completed_at = new Date(1_010_000).toISOString();
    expect(updateRate(base, next, 1_010_000)?.value).toBeNull();
  });
  it("keeps the last rate when React reprocesses the same snapshot", () => {
    const state = clientState();
    const first = {
      ...state,
      frame: frame([1, 2, 3], {
        snapshot: { ...state.frame!.snapshot, monitor_rpcs: 100 },
      }),
    };
    const baseline = updateRate(null, first, 1_000_000)!;
    const second = {
      ...first,
      frame: frame([1, 2, 3], {
        snapshot: {
          ...first.frame!.snapshot,
          seq: 2,
          completed_at: new Date(1_001_000).toISOString(),
          monitor_rpcs: 111,
        },
      }),
    };
    const calculated = updateRate(baseline, second, 1_001_000)!;
    expect(calculated.value).toBe(11);
    expect(updateRate(calculated, second, 1_002_000)?.value).toBe(11);
  });

  it("uses exact counters, accepts zero, and rejects unsafe deltas", () => {
    let state = clientState();
    const first = updateRate(null, state, 1_000_000)!;
    expect(first.value).toBeNull();
    state = {
      ...state,
      frame: frame([1, 2, 3], {
        snapshot: {
          ...state.frame!.snapshot,
          seq: 2,
          completed_at: new Date(1_001_000).toISOString(),
          monitor_rpcs: "18014398509481987",
        },
      }),
    };
    expect(updateRate(first, state, 1_001_000)?.value).toBeNull();
    const exactState = {
      ...state,
      frame: frame([1, 2, 3], {
        snapshot: {
          ...state.frame!.snapshot,
          seq: 2,
          monitor_rpcs: "9007199254740993",
        },
      }),
    };
    const exact = updateRate(null, exactState, 1_001_000)!;
    state = {
      ...exactState,
      frame: frame([1, 2, 3], {
        snapshot: {
          ...exactState.frame!.snapshot,
          seq: 3,
          completed_at: new Date(1_002_000).toISOString(),
          monitor_rpcs: "9007199254740994",
        },
      }),
    };
    expect(updateRate(exact, state, 1_002_000)?.value).toBe(1);
    const zero = updateRate(null, clientState(), 1_000_000)!;
    expect(
      updateRate(
        zero,
        clientState([1, 2, 3], {
          frame: frame([1, 2, 3], {
            snapshot: {
              ...frame().snapshot,
              seq: 2,
              completed_at: new Date(1_001_000).toISOString(),
              monitor_rpcs: 3,
            },
          }),
        }),
        1_001_000,
      )?.value,
    ).toBe(0);
  });

  it("resets on scope changes and disconnects", () => {
    const state = clientState();
    const base = updateRate(null, state, 1_000_000)!;
    const changed = { ...state, frame: frame([1, 2, 3], { generation: 2 }) };
    expect(updateRate(base, changed, 1_001_000)?.value).toBeNull();
    expect(
      updateRate(base, { ...state, connected: false }, 1_001_000)?.value,
    ).toBeNull();
  });
});

describe("deriveSummary", () => {
  it("keeps exact x, rejects prior-session snapshots and clears ambiguous leader data", () => {
    const state = clientState();
    state.frame!.snapshot.nodes![0].status!.x = "9223372036854775807";
    expect(deriveSummary(state, 1_000_000, null).leader?.status?.x).toBe(
      "9223372036854775807",
    );
    state.frame!.snapshot.session_id = "old-session";
    expect(deriveSummary(state, 1_000_000, null)).toMatchObject({
      leader: null,
      reachable: null,
      rate: null,
    });
    state.frame!.snapshot.session_id = "session-a";
    state.frame!.snapshot.nodes![1].status!.state = "Leader";
    expect(deriveSummary(state, 1_000_000, null).leader).toBeNull();
    expect(
      deriveSummary({ ...state, connected: false }, 1_000_000, null).leader,
    ).toBeNull();
  });
  it("reports observed leaders and reachability independently", () => {
    const state = clientState();
    expect(deriveSummary(state, 1_000_000, null)).toMatchObject({
      label: "观察到 Leader",
      leader: { id: 1 },
      reachable: 3,
      total: 3,
      tone: "good",
      rate: null,
    });
    const twoLeaders = {
      ...state,
      frame: frame([1, 2, 3], {
        snapshot: {
          ...state.frame!.snapshot,
          nodes: [
            sample(1),
            sample(2, { status: { ...sample(2).status!, state: "Leader" } }),
            sample(3),
          ],
        },
      }),
    };
    expect(deriveSummary(twoLeaders, 1_000_000, null)).toMatchObject({
      label: "观察到多个本地 Leader",
      tone: "warning",
    });
    const identityError = {
      ...state,
      frame: frame([1, 2, 3], {
        snapshot: {
          ...state.frame!.snapshot,
          nodes: [sample(1, { identity_ok: false }), sample(2), sample(3)],
        },
      }),
    };
    expect(deriveSummary(identityError, 1_000_000, null).label).toBe(
      "身份异常",
    );
    expect(
      deriveSummary({ ...state, connected: false }, 1_000_000, null).label,
    ).toBe("连接中断");
  });

  it("hides stale rates and ignores offline connection errors", () => {
    const state = clientState();
    const rate = {
      scope: "controller-a/session-a/1",
      seq: 1,
      completedAt: 1_000_000,
      count: 3n,
      value: 11,
    };
    const stale = {
      ...state,
      frame: frame([1, 2, 3], {
        snapshot: {
          ...state.frame!.snapshot,
          completed_at: new Date(900_000).toISOString(),
        },
      }),
    };
    expect(deriveSummary(stale, 10_000_000, rate).rate).toBeNull();
    const offline = {
      ...state,
      frame: frame([1, 2, 3], {
        snapshot: {
          ...state.frame!.snapshot,
          nodes: [
            sample(1),
            sample(2, { reachable: false, error: "connection refused" }),
            sample(3),
          ],
        },
      }),
    };
    expect(deriveSummary(offline, 1_000_000, null).label).toBe(
      "部分节点未响应",
    );
  });
});
