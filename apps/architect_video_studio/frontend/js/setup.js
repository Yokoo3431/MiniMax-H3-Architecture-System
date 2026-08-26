// Environment Center (PATCH2.8-I1)
const errEl = document.getElementById('err');
let env = null;
let plan = null;
let activeJob = null;

async function loadDesktopSettings() {
  try {
    const settings = await get('/api/system/desktop-settings');
    document.getElementById('startup-enabled').checked = Boolean(settings.startup_enabled);
    document.getElementById('tray-minimized').checked = Boolean(settings.tray_minimized);
  } catch (_) { /* optional settings must not block Environment Center */ }
}

async function saveDesktopSettings() {
  const status = document.getElementById('desktop-settings-status');
  try {
    const result = await post('/api/system/desktop-settings', {
      startup_enabled: document.getElementById('startup-enabled').checked,
      tray_minimized: document.getElementById('tray-minimized').checked,
    });
    status.textContent = result.applied === false
      ? '当前运行环境未执行 Windows 注册；设置已保存。'
      : '桌面设置已保存。';
  } catch (e) { status.textContent = e.message; }
}

// All visible Environment Center pages consume this one normalized snapshot.
// The legacy top-level fields remain in the API for older clients only.
function environmentState() { return env?.environment_state || env || {}; }

function showErr(msg) { errEl.className = 'error-banner'; errEl.style.display = 'block'; errEl.textContent = msg; }
function showNotice(msg) { errEl.className = 'notice-banner'; errEl.style.display = 'block'; errEl.textContent = msg; }

function badge(overall) {
  const cls = overall === 'READY' ? 'done' : overall === 'WARNING' ? 'warn'
    : overall === 'BLOCK' ? 'err' : 'state';
  return `<span class="badge ${cls}">${esc(overall)}</span>`;
}

function showProbeChecking() {
  const badgeEl = document.getElementById('overall-badge');
  if (badgeEl) badgeEl.innerHTML = badge('CHECKING');
  const inspector = document.getElementById('inspector');
  if (inspector) inspector.innerHTML = '<div class="muted">正在重新检查本机 GPU、驱动和托管 Runtime CUDA…</div>';
  const button = document.getElementById('recheck-btn');
  if (button) { button.disabled = true; button.textContent = 'Checking…'; }
}

function finishProbeChecking() {
  const button = document.getElementById('recheck-btn');
  if (button) { button.disabled = false; button.textContent = 'Re-check Environment'; }
}

function statusRow(k, v, cls = '') {
  return `<div class="status-row"><span class="k">${esc(k)}</span><span class="${cls}">${esc(v)}</span></div>`;
}

function shortHash(value) {
  const text = value == null ? '' : String(value);
  return text ? `${text.slice(0, 12)}…` : '—';
}

function gb(bytes) {
  return bytes == null ? 'unknown' : `${(Number(bytes) / (1024 ** 3)).toFixed(2)} GB`;
}

function componentSize(item) {
  return item.expected_size == null ? '—'
    : item.type === 'runtime' ? `~${(Number(item.expected_size) / 1e9).toFixed(2)} GB`
      : gb(item.expected_size);
}

function updateEnvironmentControls() {
  const state = environmentState();
  const allGates = Object.values(state.production_gates || state.gates || {}).every(Boolean);
  const ready = state.overall === 'READY' && allGates;
  const active = state.environment_sources?.active || {};
  const discoveryNote = document.getElementById('discovery-note');
  if (discoveryNote) {
    const source = active.source || 'configured';
    discoveryNote.textContent = source.startsWith('auto_discovered')
      ? '已自动发现并采用现有环境；不会重复下载已存在的 Runtime、模型或插件。'
      : '当前使用已配置环境；安装计划会逐项校验，完整组件将跳过下载。';
  }
  document.getElementById('continue-btn').disabled = !ready;
  document.getElementById('go-studio-btn').disabled = !ready;
  document.getElementById('open-comfy-btn').disabled = !(state.gates && state.gates.comfyui_present);
  document.getElementById('use-existing-runtime-btn').disabled = !document.getElementById('cfg-native').value.trim();
  document.getElementById('use-existing-models-btn').disabled = !document.getElementById('cfg-models').value.trim();
  const component = (id) => (plan?.components || []).find((item) => item.component_id === id);
  const setInstallState = (id, buttonId) => {
    const item = component(id);
    const button = document.getElementById(buttonId);
    if (button) button.disabled = !item || item.status === 'READY' || Boolean(plan?.blocked_reasons?.length);
  };
  setInstallState('comfyui_runtime', 'install-runtime-btn');
  setInstallState('minimax_h3_nodes', 'install-support-btn');
  setInstallState('video_helper_suite', 'install-video-btn');
  const modelIds = ['dit', 'text_encoder', 'video_vae', 'audio_vae'];
  const missingModels = modelIds.some((id) => component(id)?.status !== 'READY');
  document.getElementById('install-models-btn').disabled = !plan || !missingModels || Boolean(plan?.blocked_reasons?.length);
}

function renderInstallPlan() {
  const statusEl = document.getElementById('install-plan-status');
  const listEl = document.getElementById('install-plan');
  const consentWrap = document.getElementById('install-consent-wrap');
  const installBtn = document.getElementById('install-all-btn');
  if (!plan) {
    statusEl.textContent = '安装计划不可用。';
    listEl.innerHTML = '';
    installBtn.disabled = true;
    return;
  }
  const blocked = plan.blocked_reasons || [];
  const allReady = (plan.components || []).length > 0 &&
    (plan.components || []).every((item) => item.status === 'READY');
  statusEl.innerHTML = (allReady
    ? '<strong>All required components are already READY.</strong> No installation is required.'
    : `Download <strong>${esc(gb(plan.download_size_bytes))}</strong> · Disk required <strong>${esc(gb(plan.required_disk_bytes))}</strong> · Available <strong>${esc(plan.available_disk_gb == null ? 'unknown' : `${plan.available_disk_gb} GB`)}</strong>`)
    + (blocked.length ? `<div class="gate-note">${esc(blocked.join(', '))}</div>` : '');
  listEl.innerHTML = (plan.components || []).map((item) => {
    const ready = item.status === 'READY';
    const cls = ready ? 'ok' : item.error ? 'err' : 'warn';
    const sourceLabel = item.type === 'runtime' && item.source_status === 'TRUSTED_PINNED_SOURCE'
      ? 'Official ComfyUI GitHub Release'
      : (item.source || 'Bundled');
    const license = item.type === 'runtime' ? 'GPL-3.0' : (item.license_notice || 'Upstream license');
    return `<div class="install-item"><div class="install-item-head"><span><strong>${esc(item.name)}</strong><br><span class="small">${esc(item.version || 'pinned')}</span></span><span class="${cls}">${esc(item.status)}${item.error ? ` · ${esc(item.error)}` : ''}</span></div><div class="install-item-meta">${esc(sourceLabel)} · ${esc(componentSize(item))} · ${esc(item.source_status || 'PINNED')}<br>License: ${esc(license)}<br>Target: ${esc(item.target || '—')}</div></div>`;
  }).join('');
  consentWrap.style.display = plan.components?.some((i) => i.status !== 'READY') ? 'block' : 'none';
  installBtn.disabled = !plan.components?.some((i) => i.status !== 'READY') || blocked.includes('INSUFFICIENT_DISK');
  installBtn.style.display = allReady ? 'none' : '';
  document.getElementById('installer-panel').classList.toggle('already-ready', allReady);
  updateEnvironmentControls();
}

async function loadPlan(custom = false) {
  try {
    plan = custom ? await post('/api/system/install-plan', {
      native_root: document.getElementById('cfg-native').value.trim(),
      models_root: document.getElementById('cfg-models').value.trim(),
    }) : await get('/api/system/install-plan');
    renderInstallPlan();
  } catch (e) { document.getElementById('install-plan-status').textContent = e.message; }
}

function renderJob(job) {
  const box = document.getElementById('install-job');
  box.style.display = 'block';
  const progress = Math.max(0, Math.min(100, Number(job.progress || 0) * 100));
  box.innerHTML = `<div class="status-row"><span class="k">Install Job</span><span>${esc(job.status)}</span></div><div class="install-progress"><div style="width:${progress}%"></div></div><div class="small muted mt">${esc(job.bytes_downloaded || 0)} / ${esc(job.bytes_total || 0)} bytes${job.error ? ` · ${esc(job.error.code || 'INSTALL_FAILED')}` : ''}</div>`;
  document.getElementById('cancel-install-btn').disabled = !['QUEUED', 'INSTALLING', 'DOWNLOADING', 'VERIFYING', 'EXTRACTING'].includes(job.status);
}

async function pollJob(jobId) {
  try {
    activeJob = await get(`/api/system/install/${encodeURIComponent(jobId)}`);
    renderJob(activeJob);
    if (['READY', 'FAILED', 'CANCELLED'].includes(activeJob.status)) {
      await loadEnv();
      await loadPlan();
      return;
    }
    window.setTimeout(() => pollJob(jobId), 1000);
  } catch (e) { showErr(e.message); }
}

async function loadEnv() {
  showProbeChecking();
  try {
    env = await get('/api/system/environment');
    const state = environmentState();
    document.getElementById('overall-badge').innerHTML = badge(state.overall);
    document.getElementById('cfg-native').value = state.paths.native_root || '';
    document.getElementById('cfg-models').value = state.paths.models_root || '';
    renderGroup('system');
    updateEnvironmentControls();
    await loadPlan();
  } catch (e) { showErr(e.message); }
  finally { finishProbeChecking(); }
}

async function saveConfiguration() {
  env = await post('/api/system/configure', {
    native_root: document.getElementById('cfg-native').value.trim(),
    models_root: document.getElementById('cfg-models').value.trim(),
  });
  document.getElementById('overall-badge').innerHTML = badge(environmentState().overall);
  renderGroup('system');
  updateEnvironmentControls();
  await loadPlan(true);
}

async function startComponents(components) {
  const consent = document.getElementById('install-consent').checked;
  if (!consent) throw new Error('请先勾选许可证与下载确认。');
  const native = document.getElementById('cfg-native').value.trim();
  const models = document.getElementById('cfg-models').value.trim();
  if (!native && components.some((id) => ['comfyui_runtime', 'minimax_h3_nodes', 'video_helper_suite'].includes(id))) {
    throw new Error('请先填写 Native Runtime Path，或使用已配置的 Runtime。');
  }
  activeJob = await post('/api/system/install', {
    confirmed: true, components, native_root: native, models_root: models,
  });
  if (activeJob.job_id) {
    renderJob(activeJob);
    await pollJob(activeJob.job_id);
  } else {
    await loadEnv();
  }
}

function renderGroup(g) {
  document.querySelectorAll('#group-nav button').forEach((b) => b.classList.toggle('on', b.dataset.g === g));
  const box = document.getElementById('inspector');
  const state = environmentState();
  const s = state.system, r = state.runtime, m = state.models,
    k = state.skill || state.prompt_skill, w = state.workflows;
  const probe = state.probe || s.environment_probe || state.environment_probe || {};
  let html = `<h3>${g.toUpperCase()}</h3>`;
  if (g === 'system') {
    const hardware = s.gpu_hardware || {};
    const driver = s.driver || {};
    const runtimeCuda = s.runtime_cuda || {};
    const policy = s.hardware_policy || {};
    const runtimeClass = runtimeCuda.status === 'NOT_TESTED' ? 'warn' : runtimeCuda.ready ? 'ok' : 'err';
    const readinessClass = s.gpu_ready ? 'ok' : runtimeCuda.status === 'NOT_TESTED' ? 'warn' : 'err';
    html += statusRow('Windows', s.os)
      + statusRow('GPU Hardware', hardware.ready ? 'READY' : 'NOT DETECTED', hardware.ready ? 'ok' : 'err')
      + statusRow('GPU', hardware.name || s.gpu_name || 'UNKNOWN', hardware.ready ? 'ok' : 'warn')
      + statusRow('VRAM', hardware.vram_gb ? `${hardware.vram_gb} GB` : 'UNKNOWN', hardware.vram_gb ? 'ok' : 'warn')
      + statusRow('Driver', driver.status || 'NOT TESTED', driver.status === 'READY' ? 'ok' : driver.status === 'NOT_TESTED' ? 'warn' : 'err')
      + statusRow('Driver Version', driver.version || '—')
      + statusRow('Runtime CUDA', runtimeCuda.status || (s.cuda ? 'READY' : 'ISSUE'), runtimeClass)
      + statusRow('GPU Ready', s.gpu_ready ? 'READY' : runtimeCuda.status === 'NOT_TESTED' ? 'NOT TESTED' : 'ISSUE', readinessClass)
      + statusRow('Hardware Policy', policy.label || 'UNKNOWN', policy.status === 'SUPPORTED' ? 'ok' : policy.status === 'EXPERIMENTAL' ? 'warn' : 'err')
      + statusRow('H3 Runtime Profile', s.deployment_profile || 'AUTO', s.deployment_profile === 'COMPATIBILITY' ? 'ok' : 'warn')
      + statusRow('Profile Hardware Source', s.profile_hardware_source || '—')
      + statusRow('Probe Status', probe.probe_status === 'READY' ? 'PASS' : (probe.probe_status || 'NOT_TESTED'), probe.probe_status === 'READY' ? 'ok' : 'warn')
      + statusRow('Last Probe', probe.last_probe_finished || '—')
      + `<div class="gate-note">${esc(s.gpu_detail || policy.reason || 'Current lightweight GPU/runtime probes have not completed.')}</div>`
      + statusRow('Free Commit', `${s.free_commit} GB`,
          s.free_commit_policy?.status === 'READY' ? 'ok' :
          s.free_commit_policy?.status === 'WARNING' ? 'warn' : 'err')
      + (s.free_commit_policy?.status === 'WARNING'
          ? `<div class="gate-note">Compatibility profile：当前 Free Commit 属于警告级，不会因旧 INT8 阈值阻断；实际可用性仍以真实运行结果为准。</div>` : '')
      + statusRow('Disk', `${s.disk_free_gb} GB free`);
  } else if (g === 'runtime') {
    const support = state.support || {};
    const supportValue = (item) => {
      if (!item) return 'NOT DETECTED';
      if (item.ready) return 'READY';
      const provenance = item.provenance || {};
      return item.status === 'REVISION_MISMATCH'
        ? `REVISION MISMATCH · actual ${shortHash(provenance.actual_fingerprint)} / expected ${shortHash(provenance.expected_fingerprint)}`
        : (item.status || 'NOT READY');
    };
    const h3Provenance = support.h3?.provenance || {};
    const videoProvenance = support.video?.provenance || {};
    const upstreamReady = h3Provenance.upstream_ready === true
      || (!Object.prototype.hasOwnProperty.call(h3Provenance, 'upstream_ready') && Boolean(support.h3?.ready));
    const upstreamStatus = h3Provenance.upstream_status
      || (upstreamReady ? 'READY' : (h3Provenance.commit ? 'WRONG REVISION' : 'MISSING'));
    html += statusRow('Native ComfyUI', r.present ? 'READY' : 'MISSING', r.present ? 'ok' : 'err')
      + statusRow('ComfyUI Version', r.version || '—')
      + statusRow('Frontend', r.frontend || '—')
      + statusRow('R2A Baseline Comparison', r.baseline_comparison || '—', r.baseline_comparison === 'MATCH' ? 'ok' : 'warn')
      + statusRow('PREAD', r.pread ? 'READY' : 'MISSING', r.pread ? 'ok' : 'err')
      + statusRow('H3 Upstream', upstreamStatus, upstreamReady ? 'ok' : 'err')
      + statusRow('H3 Support Layer', supportValue(support.h3), support.h3?.ready ? 'ok' : 'err')
      + statusRow('H3 Upstream Commit', shortHash(h3Provenance.commit))
      + statusRow('H3 Managed Fingerprint', shortHash(h3Provenance.actual_fingerprint))
      + statusRow('H3 Expected Fingerprint', shortHash(h3Provenance.expected_fingerprint))
      + statusRow('Video Support', supportValue(support.video), support.video?.ready ? 'ok' : 'err')
      + statusRow('Support Dependencies', support.dependencies?.status || 'AUDIT_REQUIRED', support.dependencies?.ready ? 'ok' : 'err')
      + statusRow('Port', r.port);
    if (support.h3?.ready) {
      html += `<div class="gate-note">当前 H3 upstream、项目支持补丁和 Managed Runtime 指纹均符合本 RC 契约。三者分别显示，避免把已应用的项目补丁误判为上游版本不一致。</div>`;
    } else if (support.h3?.status === 'REVISION_MISMATCH') {
      html += `<div class="gate-note">H3 文件存在但不符合当前 RC 支持层契约，请执行 Install / Repair H3 Support Layer。</div>`;
    }
  } else if (g === 'models') {
    const h3Assets = m.h3_asset_status || {};
    const groups = h3Assets.groups || {};
    const groupStatus = (name, label) => {
      const item = groups[name] || {};
      const missing = (item.missing || []).join(', ');
      const value = item.status === 'PASS' ? 'PASS' : (missing ? `MISSING ${missing}` : (item.status || 'UNKNOWN'));
      return statusRow(label, value, item.status === 'PASS' ? 'ok' : 'err');
    };
    const discovery = m.comfy_discovery || {};
    html += statusRow('Models', `${m.ready} / ${m.count}`, m.status === 'READY' ? 'ok' : 'err')
      + statusRow('ComfyUI model discovery', discovery.status || 'NOT_CHECKED', discovery.ready ? 'ok' : 'err')
      + statusRow('H3 Assets', h3Assets.ready ? 'READY' : 'INCOMPATIBLE_RUNTIME', h3Assets.ready ? 'ok' : 'err')
      + groupStatus('tokenizer', 'Tokenizer')
      + groupStatus('processor', 'Processor')
      + groupStatus('sidecar', 'Sidecar') + '<div class="mt">';
    html += m.items.map((it) => `
      <div class="status-row"><span class="k">${esc(it.name)}<br><span class="small">${esc(it.filename)} · ${esc(it.size)}</span></span>
      <span class="${it.status === 'READY' ? 'ok' : 'err'}">${esc(it.status)}</span></div>`).join('');
    html += '</div>';
  } else if (g === 'prompt') {
    const st = k.status === 'READY' ? 'ok' : k.status === 'UPDATE_AVAILABLE' ? 'warn' : 'err';
    const installed = k.installed_revision || {};
    const pinned = k.pinned_skill_revision || {};
    html += statusRow('Official H3 Skill', k.status, st)
      + statusRow('Deployment', k.deployment_status || (k.generation_allowed ? 'INSTALLED_AND_PINNED' : 'REPAIR_REQUIRED'), k.generation_allowed ? 'ok' : 'err')
      + statusRow('Pinned Revision', k.pinned_revision || '—')
      + statusRow('Installed SKILL.md', shortHash(installed['SKILL.md']))
      + statusRow('Pinned SKILL.md', shortHash(pinned['SKILL.md']))
      + statusRow('Installed base-en.txt', shortHash(installed['references/base-en.txt']))
      + statusRow('Skill Location', k.skill_path || '—')
      + statusRow('Bridge', k.bridge || '—', k.generation_allowed ? 'ok' : 'err')
      + statusRow('Latest Upstream', k.latest_upstream === 'UNKNOWN' ? 'Not checked (pinned local revision is used)' : 'Available')
      + statusRow('Generation Allowed', k.generation_allowed ? 'Yes — ready to use' : 'Blocked — repair required', k.generation_allowed ? 'ok' : 'err');
  } else if (g === 'workflows') {
    html += statusRow('Available Workflows', `${w.ready} / ${w.count} Ready`) + '<div class="mt">';
    html += w.items.map((it) => `
      <div class="status-row"><span class="k">${esc(it.display_name)}</span>
      <span class="${it.status === 'READY' ? 'ok' : 'err'}">${esc(it.status)}</span></div>`).join('');
    html += '</div>';
  } else if (g === 'advanced') {
    const probeError = probe.probe_error || 'None — all lightweight probes passed.';
    html += `<div class="small muted">高级入口：直接打开 Native ComfyUI（节点图编辑器）。普通用户不需要。</div>
      <div class="mt">${statusRow('Native ComfyUI', r.path || '—')}</div>
      <div class="mt"><button class="btn primary" data-open-comfy-inspector>打开 Native ComfyUI（高级）</button></div>
      <div class="small muted mt">默认桌面入口不会自动打开网页；只有点击此按钮才会打开备用 ComfyUI 网页。</div>
      <div class="mt"><strong>Environment Probe Diagnostics</strong></div>
      ${statusRow('Runtime Python', probe.runtime_python_path || 'NOT FOUND')}
      ${statusRow('Torch', probe.torch_import_ok ? (probe.torch_version || 'READY') : 'IMPORT ISSUE', probe.torch_import_ok ? 'ok' : 'err')}
      ${statusRow('Torch CUDA', probe.torch_cuda_available ? (probe.torch_cuda_version || 'READY') : 'ISSUE', probe.torch_cuda_available ? 'ok' : 'err')}
      ${statusRow('Probe Error', probeError, probe.probe_error ? 'err' : 'ok')}
      <div class="small muted mt">完整 nvidia-smi / Torch stdout、stderr 和退出码已保存在本次探测结果中。</div>`;
  }
  if (g === 'advanced') {
    html += '<div class="mt"><strong>Completion Gates / Diagnostics</strong>';
    for (const [gk, gv] of Object.entries(state.gates || {})) {
      const detail = gk === 'gpu_ready' && !gv ? ` (${state.system?.gpu_detail || 'managed Runtime CUDA unavailable'})` : '';
      html += `<div class="gate-row">${gk.replace(/_/g, ' ')} — <span class="${gv ? 'ok' : 'err'}">${gv ? 'OK' : 'NOT OK'}</span>${esc(detail)}</div>`;
    }
    html += '</div>';
  }
  box.innerHTML = html;
  const inspectorComfy = box.querySelector('[data-open-comfy-inspector]');
  if (inspectorComfy) inspectorComfy.addEventListener('click', openComfyUI);
}

document.querySelectorAll('#group-nav button').forEach((b) =>
  b.addEventListener('click', () => renderGroup(b.dataset.g)));

document.getElementById('save-btn').addEventListener('click', async () => {
  try { await saveConfiguration(); } catch (e) { showErr(e.message); }
});

document.getElementById('use-existing-runtime-btn').addEventListener('click', async () => {
  try { await saveConfiguration(); } catch (e) { showErr(e.message); }
});

document.getElementById('use-existing-models-btn').addEventListener('click', async () => {
  try { await saveConfiguration(); } catch (e) { showErr(e.message); }
});

document.getElementById('recheck-btn').addEventListener('click', async () => {
  showProbeChecking();
  try {
    env = await post('/api/system/recheck', {});
    document.getElementById('overall-badge').innerHTML = badge(environmentState().overall);
    renderGroup('system');
    updateEnvironmentControls();
    await loadPlan();
  } catch (e) { showErr(e.message); }
  finally { finishProbeChecking(); }
});

document.getElementById('restart-comfyui-btn').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = '正在重启 ComfyUI…';
  try {
    const result = await post('/api/system/restart-comfyui', {});
    showNotice(result.message || 'ComfyUI 已重新启动。');
  } catch (e) {
    showErr(e.message || 'ComfyUI 重启失败。');
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
});

document.getElementById('continue-btn').addEventListener('click', () => {
  location.href = 'index.html?new=1';
});

document.getElementById('go-studio-btn').addEventListener('click', () => {
  location.href = 'index.html?new=1';
});

async function openComfyUI() {
  try {
    const info = await post('/api/system/open-comfyui', {});
    if (!info.url) throw new Error('Native ComfyUI URL is unavailable.');
    // Keep Advanced ComfyUI inside the same desktop workspace.  The native
    // shell's explicitly labelled browser-fallback button is the only path
    // that opens the system browser.
    location.href = info.url;
  } catch (e) { showErr(e.message); }
}

document.getElementById('open-comfy-btn').addEventListener('click', openComfyUI);

document.getElementById('refresh-plan-btn').addEventListener('click', () => loadPlan(true));

document.getElementById('install-all-btn').addEventListener('click', async () => {
  try { await startComponents((plan?.components || []).filter((item) => item.status !== 'READY').map((item) => item.component_id)); }
  catch (e) { showErr(e.message); }
});
document.getElementById('repair-model-paths-btn').addEventListener('click', async () => {
  const button = document.getElementById('repair-model-paths-btn');
  button.disabled = true;
  try {
    const result = await post('/api/system/repair-model-paths', {});
    showErr(`模型路径配置已生成：${result.config_path}。请重启托管 ComfyUI 后重新检查环境。`);
    await loadEnv();
  } catch (e) { showErr(e.message); }
  finally { button.disabled = false; }
});

document.getElementById('install-runtime-btn').addEventListener('click', async () => {
  try { await startComponents(['comfyui_runtime']); } catch (e) { showErr(e.message); }
});
document.getElementById('install-support-btn').addEventListener('click', async () => {
  try { await startComponents(['minimax_h3_nodes']); } catch (e) { showErr(e.message); }
});
document.getElementById('install-video-btn').addEventListener('click', async () => {
  try { await startComponents(['video_helper_suite']); } catch (e) { showErr(e.message); }
});
document.getElementById('install-models-btn').addEventListener('click', async () => {
  try { await startComponents(['dit', 'text_encoder', 'video_vae', 'audio_vae']); }
  catch (e) { showErr(e.message); }
});

document.getElementById('cancel-install-btn').addEventListener('click', async () => {
  if (!activeJob?.job_id) return;
  try {
    activeJob = await post(`/api/system/install/${encodeURIComponent(activeJob.job_id)}/cancel`, {});
    renderJob(activeJob);
  } catch (e) { showErr(e.message); }
});

document.getElementById('save-desktop-settings-btn')?.addEventListener('click', saveDesktopSettings);
loadDesktopSettings();
loadEnv();
