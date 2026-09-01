// Job Center: readable status + one-click details/retry. Internal lifecycle
// enums remain available only in the technical section.
const initialProjectId = qs('project');
const initialJobId = qs('job');
const errEl = document.getElementById('err');

function showErr(msg) { errEl.style.display = 'block'; errEl.textContent = msg; }
function jobIsTerminal(job) { return !!(job && job.is_terminal); }
function jobIsActive(job) { return !!(job && job.is_active); }
function friendlyState(job) { return job.status_label || ({COMPLETED:'完成', FAILED:'生成失败', GPU_FAILED:'生成失败', CANCELLED:'已取消', SUBMISSION_LOST:'提交未确认'}[job.state] || '生成中'); }
function formatEtaRange(job) {
  const e = job && job.estimated_time;
  if (!e || !Number.isFinite(Number(e.min_seconds)) || !Number.isFinite(Number(e.max_seconds))) return '';
  const min = Math.max(1, Math.ceil(Number(e.min_seconds) / 60));
  const max = Math.max(min, Math.ceil(Number(e.max_seconds) / 60));
  return String(min) + '–' + String(max) + ' 分钟';
}
function formatJobEta(job) {
  if (job.state === 'COMPLETED') return '已完成';
  if (['FAILED', 'GPU_FAILED', 'CANCELLED', 'SUBMISSION_LOST'].includes(job.state)) return '无需等待';
  const range = formatEtaRange(job);
  const live = Number.isFinite(Number(job.eta_seconds)) ? '剩余约 ' + Math.ceil(Number(job.eta_seconds)) + 's' : '';
  if (range) return live ? live + ' · 预计总耗时：' + range : '预计总耗时：' + range;
  return live || '正在估算剩余时间';
}
function badge(state, job) {
  const cls = state === 'COMPLETED' ? 'done' : ['FAILED','GPU_FAILED','CANCELLED','SUBMISSION_LOST'].includes(state) ? 'err' : 'warn';
  return `<span class="badge ${cls}">${esc(friendlyState(job || {state}))}</span>`;
}
function progressText(job) {
  const p = job.state === 'SUBMISSION_LOST' || job.progress == null ? '—' : `${Math.round(job.progress)}%`;
  const stage = job.state === 'SUBMISSION_LOST' ? friendlyState(job) : (job.current_stage || friendlyState(job));
  const eta = formatJobEta(job);
  return `<div class="small">${esc(p)} · ${esc(stage)} · ${esc(eta)}</div>`;
}

async function loadProjects() {
  const projects = await get('/api/projects');
  const sel = document.getElementById('project-select');
  sel.innerHTML = projects.map((p) => `<option value="${esc(p.id)}" ${p.id === initialProjectId ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
  if (projects.length) await loadJobs(sel.value);
  sel.addEventListener('change', () => { location.href = `jobs.html?project=${encodeURIComponent(sel.value)}`; });
}

async function loadJobs(pid) {
  try {
    const jobs = await get(`/api/projects/${pid}/jobs`);
    const body = document.getElementById('jobs-body');
    body.innerHTML = jobs.length ? jobs.map((j) => `
      <tr class="job-row" data-job="${esc(j.id)}" tabindex="0">
        <td>${esc(j.id)}</td><td>${esc(j.workflow)}</td><td>${badge(j.state, j)}${progressText(j)}</td>
        <td>${esc(j.seed)}</td><td>${esc(j.created_at)}</td>
        <td>${j.state === 'COMPLETED' ? `<a href="output.html?job=${esc(j.id)}" onclick="event.stopPropagation()">打开输出</a>` : `<span class="muted small">${esc(j.friendly_reason || '运行中')}</span>`}</td>
      </tr>`).join('') : '<tr><td colspan="6" class="muted">暂无任务</td></tr>';
    body.querySelectorAll('.job-row').forEach((row) => {
      const open = () => openDetail(row.dataset.job, pid);
      row.addEventListener('click', open); row.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
    });
    if (initialJobId) await openDetail(initialJobId, pid);
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
  document.getElementById('detail-summary').innerHTML = `
    <div class="kv"><span class="k">状态</span><span>${esc(detail.friendly_reason || friendlyState(detail))}</span></div>
    <div class="kv"><span class="k">进度</span><span>${esc(detail.progress == null ? '—' : Math.round(detail.progress) + '%')} · ${esc(detail.current_stage || '执行工作流')} · ${esc(formatJobEta(detail))}</span></div>
    <div class="kv"><span class="k">参数</span><span>${esc(`${p.duration ?? '—'}s · ${p.fps ?? '—'}fps · ${p.quality ?? '—'} · ${p.resolution ?? '—'}`)}</span></div>
    <div class="kv"><span class="k">提示词摘要</span><span>${esc(detail.prompt_summary || '—')}</span></div>
    ${detail.output_path ? `<div class="kv"><span class="k">视频文件</span><span class="small">${esc(detail.output_path)}</span></div>` : ''}`;
  const actions = document.getElementById('detail-actions');
  actions.innerHTML = `${['FAILED','GPU_FAILED','CANCELLED','SUBMISSION_LOST'].includes(detail.state) ? '<button class="btn primary" id="retry-job">重试</button>' : ''}
    ${detail.error_category === 'COMFYUI_CRASHED' ? '<button class="btn" id="restart-comfyui">重新启动服务</button>' : ''}
    <button class="btn" id="open-current-workflow">打开当前任务工作流</button>
    <button class="btn" id="open-study">打开 Study</button>
    ${detail.state === 'COMPLETED' ? `<a class="btn" href="output.html?job=${esc(detail.id)}">打开输出</a><button class="btn" id="open-output-folder">打开所在文件夹</button>${detail.delivery_state === 'OUTPUT_DELIVERY_FAILED' ? '<button class="btn" id="retry-output">重试复制</button>' : ''}` : ''}
    <button class="btn" id="copy-tech">复制技术详情</button>`;
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
    const target = detail.final_output_path || detail.output_path;
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
  });  document.getElementById('retry-job')?.addEventListener('click', async () => {
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

document.getElementById('refresh-btn').addEventListener('click', () => loadJobs(document.getElementById('project-select').value));
loadProjects().catch(showErr);
