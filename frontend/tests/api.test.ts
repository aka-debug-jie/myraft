import { afterEach, describe, expect, it, vi } from "vitest";
import { actionReason, fresh, scopeOf, scopeKey } from "../src/actions";
import { operate, parseJSON, request } from "../src/api";
import type { Bootstrap, ClientState, Frame } from "../src/types";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("API transport", () => {
  it("preserves unsafe integer source text and parses safe integers as numbers", () => {
    const parsed = parseJSON<{ large: string; safe: number }>(
      '{"large":9223372036854775807,"safe":42}',
    );
    expect(parsed).toEqual({ large: "9223372036854775807", safe: 42 });
  });

  it("fails closed when the reviver does not provide source text", () => {
    const nativeParse = JSON.parse;
    vi.spyOn(JSON, "parse").mockImplementation(((
      text: string,
      reviver?: (this: unknown, key: string, value: unknown) => unknown,
    ) => {
      const value = nativeParse(text);
      return reviver
        ? reviver.call({ "": value }, "", 9_223_372_036_854_776_000)
        : value;
    }) as typeof JSON.parse);
    expect(() => parseJSON("9")).toThrow(RangeError);
  });

  it("adds the read only transport header to bootstrap data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response('{"controller_id":"c"}', {
          headers: { "X-MyRaft-Read-Only": "1" },
        }),
      ),
    );
    await expect(request<Bootstrap>("/api/session")).resolves.toMatchObject({
      read_only_transport: true,
    });
  });

  it("sends operation scope and CSRF token once, and rejects unsafe seeds before sending", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response('{"id":"op"}', { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await operate(
      "generate",
      { controller_id: "c", session_id: "s", generation: 4 },
      "csrf",
      { count: 3, seed: 42 },
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/operations");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf");
    expect(JSON.parse(String(init.body))).toMatchObject({
      controller_id: "c",
      session_id: "s",
      generation: 4,
      seed: 42,
    });
    expect(() =>
      operate(
        "generate",
        { controller_id: "c", session_id: "s", generation: 4 },
        "csrf",
        { seed: Number.MAX_SAFE_INTEGER + 1 },
      ),
    ).toThrow(RangeError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("action boundaries", () => {
  const bootstrap: Bootstrap = {
    controller_id: "c",
    mode: "REAL",
    csrf_token: "",
    session: null,
    sessions: [],
    generation: 3,
    control_allowed: true,
    control_enabled: false,
    poll_ms: 1000,
    network_partition_supported: false,
  };
  const frame = {
    controller_id: "c",
    generation: 3,
    session: null,
    snapshot: { completed_at: new Date(1_000_000).toISOString() },
  } as Frame;
  const state: ClientState = {
    bootstrap,
    frame,
    connected: true,
    pending: false,
    pendingKind: null,
    error: "",
    unknownWrite: false,
    receipt: null,
    events: [],
    gap: false,
    dropped: 0,
  };

  it("keeps scope and stale/control permission checks", () => {
    expect(scopeOf(state)).toEqual({
      controller_id: "c",
      session_id: "",
      generation: 3,
    });
    expect(scopeKey(scopeOf(state))).toBe("c//3");
    expect(fresh(state, 1_000_000)).toBe(true);
    expect(actionReason({ ...state, connected: false }, "generate")).toBe(
      "连接中断，等待控制器重新连接",
    );
    expect(
      actionReason(
        { ...state, bootstrap: { ...bootstrap, read_only_transport: true } },
        "generate",
      ),
    ).toBe("当前预览入口只允许查看，操作请使用本机控制台");
  });
});
