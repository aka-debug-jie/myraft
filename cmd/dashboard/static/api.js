let csrf = '';
export function parseJSON(text) {
  return JSON.parse(text, (key, value, context) => {
    if (typeof value === 'number' && Number.isInteger(value) && !Number.isSafeInteger(value)) {
      if (context?.source === undefined) throw new RangeError('浏览器无法精确读取超出安全范围的整数');
      return context.source;
    }
    return value;
  });
}
export async function request(path, options = {}) {
  const response = await fetch(path, {cache: 'no-store', ...options});
  const text = await response.text();
  let data; try { data = parseJSON(text); } catch (error) {
    if (error instanceof RangeError) throw error;
    data = {error: text};
  }
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
export async function bootstrap() {
  const data = await request('/api/session');
  csrf = data.csrf_token;
  return data;
}
export function operate(kind, state, params = {}) {
	if (params.seed !== undefined && !Number.isSafeInteger(params.seed)) throw new RangeError('页面随机种子须为安全整数（绝对值不超过 9007199254740991）；完整 int64 种子可用 CLI');
  return request('/api/operations', {method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
    body: JSON.stringify({kind, controller_id: state.frame?.controller_id || state.bootstrap?.controller_id, session_id: state.frame?.session?.id || '',
      generation: state.frame?.generation || state.bootstrap?.generation || 1, ...params})});
}
export function logs(id, from, limit, session, generation) {
  return request(`/api/nodes/${id}/logs?` + new URLSearchParams({from, limit, session_id: session, generation}));
}
