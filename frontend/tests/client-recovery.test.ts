import { afterEach, expect, it, vi } from "vitest";
import * as api from "../src/api";
import { ConsoleClient } from "../src/client";
import { bootstrap, frame } from "./fixtures";

afterEach(() => vi.restoreAllMocks());

it("shares a pending identity refresh across faster SSE frames", async () => {
  let resolve!: (value: ReturnType<typeof bootstrap>) => void;
  const fetch = vi.spyOn(api, "bootstrap").mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const client = new ConsoleClient();
  for (let seq = 1; seq <= 12; seq++) {
    const f = frame();
    f.snapshot.seq = seq;
    client.receive(f);
  }
  expect(fetch).toHaveBeenCalledTimes(1);
  resolve(bootstrap());
  await Promise.resolve();
  expect(client.getSnapshot().bootstrap?.controller_id).toBe("controller-a");
});

it("discards a prior controller refresh without blocking the new controller", async () => {
  const resolve: ((value: ReturnType<typeof bootstrap>) => void)[] = [];
  const fetch = vi
    .spyOn(api, "bootstrap")
    .mockImplementation(() => new Promise((r) => resolve.push(r)));
  const client = new ConsoleClient();
  client.receive(frame());
  client.receive(frame(undefined, { controller_id: "controller-b" }));
  expect(fetch).toHaveBeenCalledTimes(2);
  resolve[0](bootstrap());
  await Promise.resolve();
  expect(client.getSnapshot().bootstrap).toBeNull();
  resolve[1](bootstrap("controller-b"));
  await Promise.resolve();
  expect(client.getSnapshot().bootstrap?.controller_id).toBe("controller-b");
});

it("retries an identity refresh on a later frame after a failed read", async () => {
  const fetch = vi
    .spyOn(api, "bootstrap")
    .mockRejectedValueOnce(new Error("read failed"))
    .mockResolvedValue(bootstrap());
  const client = new ConsoleClient();
  client.receive(frame());
  await Promise.resolve();
  expect(client.getSnapshot().bootstrap).toBeNull();
  const f = frame();
  f.snapshot.seq++;
  client.receive(f);
  await Promise.resolve();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(client.getSnapshot().bootstrap?.controller_id).toBe("controller-a");
});

it("keeps an unresolved write warning after unrelated verification fails or succeeds", async () => {
  vi.spyOn(Date, "now").mockReturnValue(1_000_000);
  vi.spyOn(api, "bootstrap").mockResolvedValue(bootstrap());
  const client = new ConsoleClient();
  client.receive(frame());
  await Promise.resolve();
  const operate = vi
    .spyOn(api, "operate")
    .mockRejectedValueOnce(new TypeError("write connection lost"));
  await expect(
    client.execute("generate", { count: 1, seed: 42 }),
  ).rejects.toThrow();
  operate.mockRejectedValueOnce(new api.HttpError("verify refused", 400));
  await expect(client.execute("verify")).rejects.toThrow();
  expect(client.getSnapshot().unknownWrite).toBe(true);
  operate.mockResolvedValueOnce({
    id: "verify",
    session_id: "session-a",
    generation: 1,
    kind: "verify",
    state: "queued",
    created_at: "",
    accepted: null,
    committed: null,
  });
  await client.execute("verify");
  expect(client.getSnapshot().unknownWrite).toBe(true);
  expect(client.getSnapshot().unknownWriteError).toBe("write connection lost");
  client.dismissError();
  expect(client.getSnapshot().unknownWriteError).toBe("write connection lost");
  client.receive(frame(undefined, { generation: 2 }));
  expect(client.getSnapshot().unknownWrite).toBe(false);
  expect(client.getSnapshot().unknownWriteError).toBe("");
});

it("does not revive a delayed HTTP receipt already observed and evicted by SSE", async () => {
  vi.spyOn(Date, "now").mockReturnValue(1_000_000);
  vi.spyOn(api, "bootstrap").mockResolvedValue(bootstrap());
  const client = new ConsoleClient();
  client.receive(frame());
  await Promise.resolve();
  let resolve!: (value: Awaited<ReturnType<typeof api.operate>>) => void;
  vi.spyOn(api, "operate").mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const pending = client.execute("generate", { count: 1, seed: 42 });
  const receipt = {
    id: "slow",
    session_id: "session-a",
    generation: 1,
    kind: "generate" as const,
    state: "queued",
    created_at: "",
    accepted: null,
    committed: null,
  };
  const f = frame();
  f.snapshot.seq++;
  f.operations = [
    { ...receipt, state: "succeeded", accepted: true, committed: true },
  ];
  client.receive(f);
  const next = frame();
  next.snapshot.seq += 2;
  client.receive(next);
  resolve(receipt);
  await pending;
  expect(client.getSnapshot().receipt).toBeNull();
  expect(client.getSnapshot().pending).toBe(false);
  const second = client.execute("generate", { count: 1, seed: 43 });
  resolve({ ...receipt, id: "next" });
  await second;
  expect(client.getSnapshot().receipt?.id).toBe("next");
});
