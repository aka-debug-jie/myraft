let csrf = '';
export async function request(path, options = {}) {
  const response = await fetch(path, {cache: 'no-store', ...options});
  const text = await response.text();
  let data; try { data = JSON.parse(text); } catch { data = {error: text}; }
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
export async function bootstrap() {
  const data = await request('/api/session');
  csrf = data.csrf_token;
  return data;
}
export function operate(kind, state, params = {}) {
  return request('/api/operations', {method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
    body: JSON.stringify({kind, session_id: state.frame?.session?.id || '',
      generation: state.frame?.generation || state.bootstrap?.generation || 1, ...params})});
}
export function logs(id, from, limit, session, generation) {
  return request(`/api/nodes/${id}/logs?` + new URLSearchParams({from, limit, session_id: session, generation}));
}
