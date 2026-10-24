import { scopeKey, scopeOf } from "./actions";
import type { ClientState, Operation } from "./types";

export interface ReceiptView {
  scope: string;
  id: string | null;
  consumed: boolean;
  operations: Operation[];
}

export function mergeReceipts(
  previous: ReceiptView | null,
  state: ClientState,
): ReceiptView {
  const scope = scopeKey(scopeOf(state)),
    receipt = state.receipt;
  const operations = state.frame?.operations || [];
  const current =
    receipt &&
    receipt.session_id === (state.frame?.session?.id || "") &&
    receipt.generation === state.frame?.generation
      ? receipt
      : null;
  const same = previous?.scope === scope && previous.id === current?.id;
  const consumed = Boolean(
    current &&
      (operations.some((op) => op.id === current.id) ||
        (same && previous.consumed)),
  );
  return {
    scope,
    id: current?.id || null,
    consumed,
    operations: current && !consumed ? [...operations, current] : operations,
  };
}
