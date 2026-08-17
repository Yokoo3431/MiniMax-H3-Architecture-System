// Environment Center (PATCH2.8-I1)
const errEl = document.getElementById('err');
let env = null;

function showErr(msg) { errEl.style.display = 'block'; errEl.textContent = msg; }

function badge(overall) {
  const cls = overall === 'READY' ? 'done' : overall === 'WARNING' ? 'warn'
    : overall === 'BLOCK' ? 'err' : 'state';
  return `<span class="badge ${cls}">${esc(overall)}</span>`;
}

function statusRow(k, v, cls = '') {
  return `<div class="status-row"><span class="k">${esc(k)}</span><span class="${cls}">${esc(v)}</span></div>`;
}

async function loadEnv() {
  try {
    env = await get('/api/system/environment');
    document.getElementById('overall-badge').innerHTML = badge(env.overall);
    document.getElementById('cfg-native').value = env.paths.native_root || '';
    document.getElementById('cfg-models').value = env.paths.models_root || '';
    renderGroup('system');
    const allGates = Object.values(env.gates || {}).every(Boolean);
    document.getElementById('continue-btn').disabled = !(env.overall === 'READY' && allGates);
    document.getElementById('open-comfy-btn').disabled = !(env.gates && env.gates.comfyui_present);
  } catch (e) { showErr(e.message); }
}

function renderGroup(g) {
  document.querySelectorAll('#group-nav button').forEach((b) => b.classList.toggle('on', b.dataset.g === g));
  const box = document.getElementById('inspector');
  const s = env.system, r = env.runtime, m = env.models, k = env.skill, w = env.workflows;
  let html = `<h3>${g.toUpperCase()}</h3>`;
  if (g === 'system') {
    html += statusRow('Windows', s.os) + statusRow('NVIDIA GPU', s.gpu_name)
      + statusRow('CUDA', s.cuda ? 'Ready' : 'Not available', s.cuda ? 'ok' : 'err')
      + statusRow('Free Commit', `${s.free_commit} GB`, s.free_commit >= 50 ? 'ok' : s.free_commit >= 30 ? 'warn' : 'err')
      + statusRow('Disk', `${s.disk_free_gb} GB free`);
  } else if (g === 'runtime') {
    html += statusRow('Native ComfyUI', r.present ? 'Ready' : 'Missing', r.present ? 'ok' : 'err')
      + statusRow('ComfyUI Version', r.version || '—')
      + statusRow('Frontend', r.frontend || '—')
      + statusRow('PREAD', r.pread ? 'Ready' : 'Missing', r.pread ? 'ok' : 'err')
      + statusRow('Port', r.port);
  } else if (g === 'models') {
    html += statusRow('Models', `${m.ready} / ${m.count}`) + '<div class="mt">';
    html += m.items.map((it) => `
      <div class="status-row"><span class="k">${esc(it.name)}<br><span class="small">${esc(it.filename)} · ${esc(it.size)}</span></span>
      <span class="${it.status === 'READY' ? 'ok' : 'err'}">${esc(it.status)}</span></div>`).join('');
    html += '</div>';
  } else if (g === 'prompt') {
    const st = k.status === 'READY' ? 'ok' : k.status === 'UPDATE_AVAILABLE' ? 'warn' : 'err';
    html += statusRow('Official H3 Skill', k.status, st)
      + statusRow('Pinned Revision', (k.pinned_revision || '').slice(0, 12))
      + statusRow('Installed Revision', (k.installed_revision && k.installed_revision.SKILL.md ? k.installed_revision.SKILL.md.slice(0, 12) : '—'))
      + statusRow('Latest Upstream', k.latest_upstream === 'UNKNOWN' ? 'UNKNOWN' : '—')
      + statusRow('Generation Allowed', k.generation_allowed ? 'Yes' : 'Blocked', k.generation_allowed ? 'ok' : 'err');
  } else if (g === 'workflows') {
    html += statusRow('Available Workflows', `${w.ready} / ${w.count} Ready`) + '<div class="mt">';
    html += w.items.map((it) => `
      <div class="status-row"><span class="k">${esc(it.display_name)}</span>
      <span class="${it.status === 'READY' ? 'ok' : 'err'}">${esc(it.status)}</span></div>`).join('');
    html += '</div>';
  } else if (g === 'advanced') {
    html += `<div class="small muted">高级入口：直接打开 Native ComfyUI（节点图编辑器）。普通用户不需要。</div>
      <div class="mt">${statusRow('Native ComfyUI', r.path || '—')}</div>`;
  }
  html += '<div class="mt"><strong>Completion Gates</strong>';
  for (const [gk, gv] of Object.entries(env.gates || {})) {
    html += `<div class="gate-row">${gk.replace(/_/g, ' ')} — <span class="${gv ? 'ok' : 'err'}">${gv ? 'OK' : 'NOT OK'}</span></div>`;
  }
  html += '</div>';
  box.innerHTML = html;
}

document.querySelectorAll('#group-nav button').forEach((b) =>
  b.addEventListener('click', () => renderGroup(b.dataset.g)));

document.getElementById('save-btn').addEventListener('click', async () => {
  try {
    env = await post('/api/system/configure', {
      native_root: document.getElementById('cfg-native').value.trim(),
      models_root: document.getElementById('cfg-models').value.trim(),
    });
    document.getElementById('overall-badge').innerHTML = badge(env.overall);
    renderGroup('system');
    const allGates = Object.values(env.gates || {}).every(Boolean);
    document.getElementById('continue-btn').disabled = !(env.overall === 'READY' && allGates);
    document.getElementById('open-comfy-btn').disabled = !(env.gates && env.gates.comfyui_present);
  } catch (e) { showErr(e.message); }
});

document.getElementById('recheck-btn').addEventListener('click', async () => {
  try {
    env = await post('/api/system/recheck', {});
    document.getElementById('overall-badge').innerHTML = badge(env.overall);
    renderGroup('system');
    const allGates = Object.values(env.gates || {}).every(Boolean);
    document.getElementById('continue-btn').disabled = !(env.overall === 'READY' && allGates);
  } catch (e) { showErr(e.message); }
});

document.getElementById('continue-btn').addEventListener('click', () => {
  location.href = 'index.html';
});

document.getElementById('open-comfy-btn').addEventListener('click', async () => {
  try {
    const info = await post('/api/system/open-comfyui', {});
    alert(`Advanced entry: ${info.advanced_entry}`);
  } catch (e) { showErr(e.message); }
});

loadEnv();
