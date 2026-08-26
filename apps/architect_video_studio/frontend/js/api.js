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
