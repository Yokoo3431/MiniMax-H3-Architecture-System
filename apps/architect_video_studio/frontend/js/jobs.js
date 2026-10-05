// Job Center: readable status + one-click details/retry. Internal lifecycle
// enums remain available only in the technical section.
const initialProjectId = qs('project');
const initialJobId = qs('job');
let activeProjectId = initialProjectId || '';
const errEl = document.getElementById('err');
const selectionHintEl = document.getElementById('selection-hint');

function showErr(msg) { errEl.style.display = 'block'; errEl.textContent = friendlyError(msg); }
function showProjectHint(msg) {
  if (!selectionHintEl) return;
  selectionHintEl.textContent = msg;
  selectionHintEl.hidden = !msg;
}
function jobIsTerminal(job) { return !!(job && job.is_terminal); }
function jobIsActive(job) { return !!(job && job.is_active); }
const RESULT_RECOVERY_FAILURE_STAGES = new Set([
  'SAVE_VIDEO_CONTRACT', 'SAVE_VIDEO_NODE', 'COMFY_HISTORY',
  'OUTPUT_DISCOVERY', 'MEDIA_PROBE', 'PACKAGING', 'RESULT_PERSISTENCE',
  'OUTPUT_DELIVERY', 'RECOVERY',
]);
function hasStrongResultRecoveryIdentity(job) {
  if (!job || job.runtime !== 'native' || job.cancelled || !job.prompt_id) return false;
  if (!['COMPLETED', 'FAILED', 'GPU_FAILED', 'SUBMISSION_LOST'].includes(job.state)) return false;
  if (!/^[a-f0-9]{64}$/i.test(String(job.execution_workflow_sha256 || ''))) return false;
  const target = job.runtime_target;
  const identity = job.execution_trace?.runtime_identity || {};
  const expected = target === 'experimental'
    ? {runtimeId: 'experimental-h3-8190', role: 'experimental', port: 8190, version: '0.36.0'}
    : target === 'production'
      ? {runtimeId: 'production-h3-8189', role: 'production', port: 8189, version: '0.33.1'}
      : null;
  return !!expected
    && Number(identity.identity_schema_version) >= 2
    && identity.runtime_id === expected.runtimeId
    && identity.runtime_role === expected.role
    && identity.backend === 'comfyui'
    && Number(identity.port) === expected.port
    && identity.comfyui_version === expected.version
    && !!identity.endpoint_fingerprint
    && !!identity.runtime_config_fingerprint
    && !!identity.output_root_fingerprint
    && (target !== 'experimental'
      || identity.comfyui_git_sha === 'ee71d5c4993f29086b27fde1629a945ae48425bf');
}
function hasResultPipelineRecoveryFailure(job) {
  const pipeline = job?.result_pipeline || {};
  if (RESULT_RECOVERY_FAILURE_STAGES.has(pipeline.current_stage)
      && pipeline.status === 'FAILED') return true;
  return (pipeline.events || []).some((event) =>
    RESULT_RECOVERY_FAILURE_STAGES.has(event?.stage) && event?.status === 'FAILED');
}
async function shouldOfferResultRecovery(job) {
  if (!hasStrongResultRecoveryIdentity(job)) return false;
  if (job.state === 'COMPLETED') {
    try {
      const result = await get(`/api/jobs/${encodeURIComponent(job.id)}/result`);
      return result?.output?.available === false;
    } catch (error) {
      // Only the explicit missing-output contract makes a completed Job
      // eligible; transient/API errors must not create a misleading action.
      return /^OUTPUT_ERROR:/i.test(String(error?.message || error));
    }
  }
  return hasResultPipelineRecoveryFailure(job);
}
function friendlyState(job) {
  return job.status_label || ({QUEUED:'排队中', SUBMITTED:'已提交', RUNNING:'运行中', GENERATING:'生成中', RECONCILING:'整理输出', COMPLETED:'完成', FAILED:'生成失败', GPU_FAILED:'生成失败', CANCELLED:'已取消', SUBMISSION_LOST:'提交未确认'}[job.state] || '生成中');
}
function formatEtaRange(job) {
  const e = job && job.estimated_time;
  if (!e || !Number.isFinite(Number(e.min_seconds)) || !Number.isFinite(Number(e.max_seconds))) return '';
  const min = Math.max(1, Math.ceil(Number(e.min_seconds) / 60));
  const max = Math.max(min, Math.ceil(Number(e.max_seconds) / 60));
  return String(min) + '–' + String(max) + ' 分钟';
}
function formatJobEta(job) {
  if (job.state === 'COMPLETED') return '已完成';
  if (['FAILED', 'GPU_FAILED'].includes(job.state)) return '已停止';
  if (job.state === 'CANCELLED') return '已取消';
  if (job.state === 'SUBMISSION_LOST') return '提交状态待核验';
  const range = formatEtaRange(job);
  const etaSeconds = Number(job.eta_seconds);
  const live = Number.isFinite(etaSeconds) && etaSeconds > 0 ? '剩余约 ' + Math.ceil(etaSeconds) + 's' : '';
  if (range) return live ? live + ' · 预计总耗时：' + range : '预计总耗时：' + range;
  return live || '正在估算剩余时间';
}
function outputFolderPath(outputPath) {
  const separator = String.fromCharCode(92);
  let raw = String(outputPath || '').trim();
  while (raw.endsWith('/') || raw.endsWith(separator)) raw = raw.slice(0, -1);
  const slash = Math.max(raw.lastIndexOf('/'), raw.lastIndexOf(separator));
  return slash > 0 ? raw.slice(0, slash) : '';
}
function badge(state, job) {
  const cls = state === 'COMPLETED' ? 'done' : ['FAILED','GPU_FAILED','CANCELLED','SUBMISSION_LOST'].includes(state) ? 'err' : 'warn';
  return `<sl-badge class="badge ${cls}" variant="${cls === 'done' ? 'success' : cls === 'err' ? 'danger' : 'neutral'}" pill>${esc(friendlyState(job || {state}))}</sl-badge>`;
}
function progressText(job) {
  const p = job.state === 'SUBMISSION_LOST' || job.progress == null ? '—' : `${Math.round(job.progress)}%`;
  const stage = job.state === 'SUBMISSION_LOST' ? friendlyState(job) : (job.current_stage || friendlyState(job));
  const eta = formatJobEta(job);
  if (['FAILED', 'GPU_FAILED'].includes(job.state)) {
    const lastProgress = p === '—' ? '进度未知' : `失败前 ${p}`;
    return `<div class="small">${esc(lastProgress)} · 最后记录阶段：${esc(stage)} · ${esc(eta)}</div>`;
  }
  if (job.state === 'CANCELLED') {
    const lastProgress = p === '—' ? '取消时进度未知' : `取消时进度 ${p}`;
    return `<div class="small">${esc(lastProgress)} · 最后记录阶段：${esc(stage)} · ${esc(eta)}</div>`;
  }
  if (job.state === 'SUBMISSION_LOST') {
    return `<div class="small">${esc(eta)} · 不会自动重新提交</div>`;
  }
  return `<div class="small">${esc(p)} · ${esc(stage)} · ${esc(eta)}</div>`;
}

async function loadProjects() {
  const projects = await get('/api/projects');
  const sel = document.getElementById('project-select');
  sel.innerHTML = projects.map((p) => `<sl-option value="${esc(p.id)}" ${p.id === initialProjectId ? 'selected' : ''}>${esc(p.name)}</sl-option>`).join('');
  let selected = projects.find((p) => p.id === initialProjectId)?.id || '';
  if (!selected && initialJobId) {
    try {
      const detail = await get(`/api/jobs/${encodeURIComponent(initialJobId)}/detail`);
      selected = projects.find((p) => p.id === detail.project?.id)?.id || '';
    } catch (_) { /* the empty state below is the truthful fallback */ }
  }
  activeProjectId = selected;
  if (selected) {
    // Do not depend on the custom element having reflected its value yet.
    sel.value = selected;
    showProjectHint('');
    await loadJobs(selected);
  } else {
    showProjectHint(projects.length
      ? '请选择一个 Study 查看任务。'
      : '还没有 Study，请先在 Home 创建一个 Study。');
  }
  sel.addEventListener('change', () => {
    activeProjectId = sel.value || activeProjectId;
    if (activeProjectId) location.href = `jobs.html?project=${encodeURIComponent(activeProjectId)}`;
  });
}

async function loadJobs(pid) {
  if (!pid) { showProjectHint('请先选择一个 Study 查看任务。'); return; }
  try {
    const body = document.getElementById('jobs-body');
    body.innerHTML = '<tr><td colspan="6" class="muted">正在加载任务…</td></tr>';
    const jobs = await get(`/api/projects/${pid}/jobs`);
    body.innerHTML = jobs.length ? jobs.map((j) => `
      <tr class="job-row" data-job="${esc(j.id)}" tabindex="0">
        <td data-label="Job">${esc(j.id)}</td><td data-label="Workflow">${esc(j.workflow)}</td><td data-label="状态">${badge(j.state, j)}${progressText(j)}</td>
        <td data-label="Seed">${esc(j.seed)}</td><td data-label="创建时间">${esc(j.created_at)}</td>
        <td data-label="操作">${j.state === 'COMPLETED' ? `<a href="output.html?project=${encodeURIComponent(pid)}&job=${esc(j.id)}" onclick="event.stopPropagation()">打开输出</a>` : `<span class="muted small">${esc(j.friendly_reason || friendlyState(j))}</span>`}</td>
      </tr>`).join('') : '<tr><td colspan="6" class="muted">暂无任务</td></tr>';
    body.querySelectorAll('.job-row').forEach((row) => {
      const open = () => openDetail(row.dataset.job, pid);
      row.addEventListener('click', open); row.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
    });
    if (initialJobId && jobs.some((j) => String(j.id) === String(initialJobId))) await openDetail(initialJobId, pid);
    if (jobs.some((j) => jobIsActive(j))) setTimeout(() => loadJobs(pid), 2000);
  } catch (e) { showErr(e.message); }
}

async function openDetail(jobId, pid) {
  const detail = await get(`/api/jobs/${encodeURIComponent(jobId)}/detail`);
  const panel = document.getElementById('job-detail'); panel.style.display = 'block';
  document.getElementById('detail-title').textContent = `任务详情 · ${detail.id}`;
  document.getElementById('detail-subtitle').textContent = `${detail.workflow} · ${detail.created_at}`;
  document.getElementById('detail-status').innerHTML = badge(detail.state, detail);
  document.getElementById('detail-reference').innerHTML = detail.reference
    ? `<img class="job-reference-thumb" src="${esc(detail.reference.preview_url)}" alt="参考图"><div class="small muted mt">${esc(detail.reference.filename || '')}</div>`
    : '<div class="muted">无参考图</div>';
  const p = detail.parameters || {};
  const trace = detail.technical_details?.execution_trace || {};
  document.getElementById('detail-summary').innerHTML = `
    <div class="kv"><span class="k">状态</span><span>${esc(detail.friendly_reason || friendlyState(detail))}</span></div>
    <div class="kv"><span class="k">进度</span><span>${esc(detail.progress == null ? '—' : Math.round(detail.progress) + '%')} · ${esc(detail.current_stage || '执行工作流')} · ${esc(formatJobEta(detail))}</span></div>
    <div class="kv"><span class="k">参数</span><span>${esc(`${p.duration ?? '—'}s · ${p.fps ?? '—'}fps · ${p.quality ?? '—'} · ${p.resolution ?? '—'}`)}</span></div>
    <div class="kv"><span class="k">A4 配置</span><span>${esc(`${String(trace.quality_profile || p.quality || '—').toUpperCase()} · ${trace.architecture_profile || '—'} · ${trace.status || '—'}`)}</span></div>
    <div class="kv"><span class="k">提示词摘要</span><span>${esc(detail.prompt_summary || '—')}</span></div>
    ${detail.output_path ? `<div class="kv"><span class="k">视频文件</span><span class="small">${esc(detail.output_path)}</span></div>` : ''}`;
  const actions = document.getElementById('detail-actions');
  const offerResultRecovery = await shouldOfferResultRecovery(detail);
  actions.innerHTML = `${['FAILED','GPU_FAILED','CANCELLED','SUBMISSION_LOST'].includes(detail.state) ? '<sl-button class="btn primary" id="retry-job">重试</sl-button>' : ''}
    ${offerResultRecovery ? '<sl-button class="btn" id="recover-result" aria-describedby="recover-result-note">恢复已有结果（不会重新生成）</sl-button>' : ''}
    ${detail.error_category === 'COMFYUI_CRASHED' ? '<sl-button class="btn" id="restart-comfyui">重新启动服务</sl-button>' : ''}
    <sl-button class="btn" id="open-current-workflow">打开当前任务工作流</sl-button>
    <sl-button class="btn" id="open-study">打开 Study</sl-button>
    ${offerResultRecovery ? '<span class="small muted" id="recover-result-note">仅核验这次已提交任务并恢复可验证输出；不会创建新任务或提交生成。</span>' : ''}
    ${detail.state === 'COMPLETED' ? `<a class="btn" href="output.html?project=${encodeURIComponent(pid)}&job=${esc(detail.id)}">打开输出</a><sl-button class="btn" id="open-output-folder">打开所在文件夹</sl-button>${detail.delivery_state === 'OUTPUT_DELIVERY_FAILED' ? '<sl-button class="btn" id="retry-output">重试复制</sl-button>' : ''}` : ''}
    <sl-button class="btn" id="copy-tech">复制技术详情</sl-button>`;
  document.getElementById('detail-technical').textContent = JSON.stringify(detail.technical_details || {}, null, 2);
  document.getElementById('open-study')?.addEventListener('click', () => { location.href = `workspace.html?project=${encodeURIComponent(pid)}`; });
  document.getElementById('open-current-workflow')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = '正在准备…';
    try {
      const info = await post('/api/system/open-comfyui', {job_id: detail.id});
      location.href = info.url;
    } catch (e) {
      showErr(e.message || '当前任务工作流打开失败');
      button.disabled = false;
      button.textContent = '打开当前任务工作流';
    }
  });
  document.getElementById('copy-tech')?.addEventListener('click', async () => { await navigator.clipboard?.writeText(document.getElementById('detail-technical').textContent || ''); });
  document.getElementById('open-output-folder')?.addEventListener('click', async () => {
    const target = outputFolderPath(detail.final_output_path || detail.output_path);
    if (!target) return;
    try { await post('/api/system/open-path', {path: target}); } catch (e) { showErr(e.message); }
  });
  document.getElementById('retry-output')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await post(`/api/jobs/${encodeURIComponent(detail.id)}/retry-output`, {});
      await openDetail(detail.id, pid);
    } catch (e) { showErr(e.message || '复制视频失败'); button.disabled = false; }
  });
  document.getElementById('recover-result')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = '正在核验并恢复…';
    try {
      await post(`/api/jobs/${encodeURIComponent(detail.id)}/recover-result`, {});
      await openDetail(detail.id, pid);
    } catch (e) {
      showErr('恢复未完成；本次操作没有重新提交生成。请查看任务技术详情。');
      button.disabled = false;
      button.textContent = '恢复已有结果（不会重新生成）';
    }
  });
  document.getElementById('retry-job')?.addEventListener('click', async () => {
    try { const next = await post(`/api/jobs/${encodeURIComponent(detail.id)}/retry`, {}); location.href = `jobs.html?project=${encodeURIComponent(pid)}&job=${encodeURIComponent(next.id)}`; }
    catch (e) { showErr(e.message); }
  });
  document.getElementById('restart-comfyui')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = '正在启动…';
    try {
      const result = await post('/api/system/restart-comfyui', {});
      alert(result.message || 'ComfyUI 服务已重新启动。');
      await loadJobs(pid);
    } catch (e) {
      showErr(e.message || '服务重新启动失败');
      button.disabled = false;
      button.textContent = '重新启动服务';
    }
  });
}

document.getElementById('refresh-btn').addEventListener('click', () => loadJobs(activeProjectId || document.getElementById('project-select').value));
loadProjects().catch(showErr);
