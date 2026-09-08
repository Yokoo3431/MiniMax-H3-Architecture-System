// Architect Video Studio - thin API client (PATCH2.6-B mock contract)
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let payload = {};
  try { payload = await res.json(); } catch (_) { /* non-json */ }
  if (!res.ok || payload.ok === false) {
    throw new Error(payload.error || `HTTP ${res.status}`);
  }
  return payload.data;
}

const get = (p) => api('GET', p);
const post = (p, b) => api('POST', p, b || {});
const patch = (p, b) => api('PATCH', p, b || {});

function qs(name) {
  return new URLSearchParams(window.location.search).get(name);
}

function esc(text) {
  const d = document.createElement('div');
  d.textContent = text == null ? '' : String(text);
  return d.innerHTML;
}

// Keep normal product surfaces readable when an API returns a technical
// failure. Detailed diagnostics remain available in advanced panels.
function friendlyError(error, fallback = '操作失败，请稍后重试。') {
  const raw = typeof error === 'string' ? error : (error && error.message ? String(error.message) : '');
  if (!raw) return fallback;
  if (/HTTP 404|not found|不存在|未找到/i.test(raw)) return '找不到请求的内容，请返回上一级并重新选择。';
  if (/missing job|job.*required|缺少 job|缺少任务/i.test(raw)) return '请先从 Jobs 选择一个具体任务。';
  if (/not.*completed|no output|尚未生成|未生成/i.test(raw)) return '该任务目前还没有可查看的输出，请返回 Jobs 查看任务状态。';
  return raw;
}
