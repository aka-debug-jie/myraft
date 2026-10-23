import type {
  Bootstrap,
  Operation,
  OperationKind,
  OperationParams,
  Scope,
} from "./types";

export class HttpError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

export function parseJSON<T>(text: string): T {
  const reviver = (
    _key: string,
    value: unknown,
    context?: { source?: string },
  ): unknown => {
    if (
      typeof value === "number" &&
      Number.isInteger(value) &&
      !Number.isSafeInteger(value)
    ) {
      if (context?.source === undefined)
        throw new RangeError("浏览器无法精确读取超出安全范围的整数");
      return context.source;
    }
    return value;
  };
  return JSON.parse(text, reviver as never) as T;
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const deadline = AbortSignal.timeout(10_000);
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    signal: options.signal
      ? AbortSignal.any([deadline, options.signal])
      : deadline,
  });
  const text = await response.text();
  let data: unknown;
  try {
    data = parseJSON<unknown>(text);
  } catch (error) {
    if (response.ok) throw error;
    data = { error: text };
  }
  if (!response.ok) {
    const message =
      typeof data === "object" &&
      data !== null &&
      "error" in data &&
      typeof data.error === "string"
        ? data.error
        : `HTTP ${response.status}`;
    throw new HttpError(message, response.status);
  }
  if (path === "/api/session" && typeof data === "object" && data !== null) {
    (data as Bootstrap).read_only_transport =
      response.headers.get("X-MyRaft-Read-Only") === "1";
  }
  return data as T;
}

export function bootstrap(): Promise<Bootstrap> {
  return request<Bootstrap>("/api/session");
}

export function operate(
  kind: OperationKind,
  scope: Scope,
  token: string,
  params: OperationParams = {},
): Promise<Operation | { state: "enabled" }> {
  if (params.seed !== undefined && !Number.isSafeInteger(params.seed)) {
    throw new RangeError("页面随机种子须为安全整数；完整 int64 种子可用 CLI");
  }
  return request<Operation | { state: "enabled" }>("/api/operations", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
    body: JSON.stringify({
      ...params,
      kind,
      controller_id: scope.controller_id,
      session_id: scope.session_id,
      generation: scope.generation,
    }),
  });
}
