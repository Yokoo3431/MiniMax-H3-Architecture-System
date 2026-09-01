// Studio workspace: one simple product flow backed by canonical Study/Job state.
// OfficialSkillAdapter remains an explicit legacy compatibility provider;
// normal product generation uses the universal offline-first Prompt Engine.
const projectId = qs('project');
if (!projectId) location.href = 'index.html';

const errEl = document.getElementById('err');
let project = null;
let catalog = null;
let intent = null;
let prompt = null;
let study = null;
let refs = [];
let selectedRef = null;
let pendingFile = null;
let pollTimer = null;
let promptTimer = null;
let promptRequestSerial = 0;
let providerCatalog = [];

const VIDEO_TYPES = [
  ['01_Exterior_Hero', 'Exterior Hero'],
  ['02_Day_Night_Transition', 'Day / Night Transition'],
  ['03_Material_Detail', 'Material Detail'],
  ['04_Drone_Aerial', 'Drone Aerial'],
  ['05_Slow_Walkthrough', 'Slow Walkthrough'],
];
const TYPE_HELP = {
  '01_Exterior_Hero': '建筑外观主镜头，适合入口、立面与整体空间展示。',
  '02_Day_Night_Transition': '日夜与灯光氛围变化，适合表现时间和照明设计。',
  '03_Material_Detail': '材质与细部镜头，适合墙面、节点和构造质感。',
  '04_Drone_Aerial': '航拍与总图展示，适合建筑群、景观和场地关系。',
  '05_Slow_Walkthrough': '人视缓慢漫游，适合室内空间与动线体验。',
};
const QUALITY_DEFAULTS = {
  draft: { resolution: '832x480', sampler_mode: 'res_multistep' },
  standard: { resolution: '1024x576', sampler_mode: 'euler' },
  high: { resolution: '1344x768', sampler_mode: 'euler' },
};
const STATE_LABELS = {
  CREATED: '准备中', REFERENCE_PENDING: '等待参考图', REFERENCE_APPROVED: '准备中',
  PROMPT_REVIEW: '准备中', PROMPT_NEEDS_CONFIRMATION: '准备中', USER_CONFIRM: '可以生成',
  GPU_RUNNING: '生成中', QUALITY_CHECK: '生成中', COMPLETED: '已完成',
  FAILED: '生成失败', GPU_FAILED: '生成失败', GENERATING: '生成中',
  READY_TO_GENERATE: '可以生成',
};

function showErr(msg) { errEl.style.display = 'block'; errEl.textContent = msg; }
function clearErr() { errEl.style.display = 'none'; errEl.textContent = ''; }
function value(id) { return document.getElementById(id).value; }
function currentWorkflow() { return value('video-type'); }
function currentParams() {
  const raw = {
    duration: parseFloat(value('param-duration')),
    resolution: value('param-resolution'),
    fps: parseInt(value('param-fps'), 10),
    aspect_ratio: value('param-aspect'),
    quality: value('param-quality'),
    generation_speed: value('param-speed'),
    sampler_mode: value('param-sampler'),
    velocity_cache: document.getElementById('param-velocity').checked,
    cache_dit: document.getElementById('param-cache-dit').checked,
  };
  const seed = value('param-seed').trim();
  const steps = value('param-steps').trim();
  if (seed) raw.seed = parseInt(seed, 10);
  if (steps) raw.steps = parseInt(steps, 10);
  return raw;
}
function stateLabel(state) { return STATE_LABELS[state] || '准备中'; }
function jobIsTerminal(job) { return !!(job && job.is_terminal); }
function jobIsActive(job) { return !!(job && job.is_active); }
function formatEtaRange(job) {
  const e = job && job.estimated_time;
  if (!e || !Number.isFinite(Number(e.min_seconds)) || !Number.isFinite(Number(e.max_seconds))) return '';
  const min = Math.max(1, Math.ceil(Number(e.min_seconds) / 60));
  const max = Math.max(min, Math.ceil(Number(e.max_seconds) / 60));
  return String(min) + '–' + String(max) + ' 分钟';
}
function formatJobEta(job) {
  if (!job || jobIsTerminal(job)) return job && job.state === 'COMPLETED' ? '已完成' : '无需等待';
  const range = formatEtaRange(job);
  const live = Number.isFinite(Number(job.eta_seconds)) ? '剩余约 ' + Math.ceil(Number(job.eta_seconds)) + 's' : '';
  if (range) return live ? live + ' · 预计总耗时：' + range : '预计总耗时：' + range;
  return live || '正在估算剩余时间';
}

async function refreshStudy() {
  study = await get(`/api/projects/${projectId}/study`);
  return study;
}

async function loadAll() {
  const [detail, c] = await Promise.all([get(`/api/projects/${projectId}`), get('/api/catalog')]);
  project = detail.project || detail; catalog = c;
  study = detail.study || await refreshStudy();
  refs = detail.references || [];
  intent = detail.intent || null;
  prompt = detail.prompt || null;
  if (intent && intent.natural_language) document.getElementById('intent-text').value = intent.natural_language;
  await loadProviderCatalog();
  renderHeader(); renderVideoTypes(); renderParams(); renderRefs(); renderPrompt(); renderOutputDirectory(); updateGate(); refreshEstimate();
  if (selectedRef && selectedRef.state === 'APPROVED'
      && document.getElementById('intent-text').value.trim()
      && !(study && study.prompt_current)) schedulePromptRefresh(80);
  pollJobs();
}

async function loadProviderCatalog() {
  try {
    providerCatalog = await get('/api/prompt/providers');
    const selected = value('prompt-engine') || 'AUTO';
    const config = providerCatalog.find((item) => item.provider === selected);
    if (config) {
      document.getElementById('provider-executable').value = config.executable || '';
      document.getElementById('provider-arguments').value = (config.arguments || []).join('\n');
      document.getElementById('provider-base-url').value = config.base_url || '';
      document.getElementById('provider-model').value = config.model || '';
      document.getElementById('provider-api-key-env').value = config.api_key_env || '';
    }
    const option = document.querySelector(`#prompt-engine option[value="${selected}"]`);
    if (option && config && config.available === false && !option.dataset.unavailable) {
      option.textContent += '（未配置）'; option.dataset.unavailable = '1';
    }
  } catch (_) { /* provider configuration is optional; offline mode remains usable */ }
}

function providerConfig() {
  return {
    provider: value('prompt-engine') === 'AUTO' ? 'OFFLINE_COMPILER' : value('prompt-engine'),
    executable: value('provider-executable').trim(),
    arguments: value('provider-arguments').split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
    base_url: value('provider-base-url').trim(),
    model: value('provider-model').trim(),
    api_key_env: value('provider-api-key-env').trim(),
    multimodal_capable: !!document.getElementById('prompt-image-consent')?.checked,
  };
}

async function saveProvider() {
  const status = document.getElementById('provider-status');
  try {
    const saved = await post('/api/prompt/providers/configure', providerConfig());
    status.textContent = `已保存 · ${saved.model || saved.executable || saved.provider}`;
    providerCatalog = await get('/api/prompt/providers');
  } catch (e) { status.textContent = e.message || '保存失败'; }
}

async function testProvider() {
  const status = document.getElementById('provider-status');
  try {
    const result = await post('/api/prompt/providers/test', providerConfig());
    status.textContent = result.ok ? `连接成功 · ${result.model || result.message}` : (result.message || '连接失败');
  } catch (e) { status.textContent = e.message || '测试失败'; }
}

function detectProvider() {
  const provider = value('prompt-engine');
  const item = providerCatalog.find((entry) => entry.provider === provider);
  const input = document.getElementById('provider-executable');
  const status = document.getElementById('provider-status');
  if (item && item.executable) {
    input.value = item.executable;
    status.textContent = item.available ? '已检测到可执行文件（尚未启动）' : '已记录，但当前不可运行';
  } else {
    status.textContent = '未检测到，请填写可执行文件路径';
  }
}

function renderHeader() {
  document.getElementById('task-name').textContent = project.name || 'Architect Video Studio';
  document.getElementById('task-meta').textContent =
    `${project.project_type || '建筑视频'} · 参考图 → 视频类型 → 意图 → 参数 → 生成`;
  const badge = document.getElementById('task-state');
  const state = (study && study.current_state) || project.state;
  badge.textContent = stateLabel(state);
  badge.className = `badge ${['COMPLETED','USER_CONFIRM','READY_TO_GENERATE'].includes(state) ? 'done' : ['FAILED','GPU_FAILED'].includes(state) ? 'err' : state === 'GPU_RUNNING' ? 'warn' : 'state'}`;
}

function renderVideoTypes() {
  const select = document.getElementById('video-type');
  const selected = (intent && intent.selected_workflow) || VIDEO_TYPES[0][0];
  select.innerHTML = VIDEO_TYPES.map(([id, label]) =>
    `<option value="${esc(id)}" ${id === selected ? 'selected' : ''}>${esc(label)}</option>`).join('');
  document.getElementById('video-type-help').textContent = TYPE_HELP[selected];
}

function renderParams() {
  const duration = document.getElementById('param-duration');
  duration.innerHTML = Array.from({length: 12}, (_, i) => i + 4)
    .map((seconds) => `<option value="${seconds}">${seconds} 秒</option>`).join('');
  const resolution = document.getElementById('param-resolution');
  resolution.innerHTML = ['832x480', '1024x576', '1344x768']
    .map((v) => `<option value="${v}" ${v === '1024x576' ? 'selected' : ''}>${v.replace('x', '×')}</option>`).join('');
  const saved = (prompt && prompt.generation_parameters) || {};
  if (saved.duration) duration.value = String(saved.duration);
  if (saved.resolution) resolution.value = saved.resolution;
  if (saved.fps != null) document.getElementById('param-fps').value = String(saved.fps);
  if (saved.aspect_ratio) document.getElementById('param-aspect').value = saved.aspect_ratio;
  if (saved.quality) document.getElementById('param-quality').value = saved.quality;
  if (saved.generation_speed) document.getElementById('param-speed').value = saved.generation_speed;
  const qualityDefaults = QUALITY_DEFAULTS[value('param-quality')];
  document.getElementById('param-sampler').value = saved.sampler_mode ||
    (value('param-speed') === 'auto' ? 'euler' : qualityDefaults.sampler_mode);
  if (saved.seed != null) document.getElementById('param-seed').value = String(saved.seed);
  if (saved.sigma_points != null) document.getElementById('param-steps').value = String(saved.sigma_points);
  document.getElementById('param-velocity').checked = !!saved.velocity_cache;
  document.getElementById('param-cache-dit').checked = !!saved.cache_dit;
  syncViewportParams();
}

async function refreshEstimate() {
  const note = document.getElementById('estimate-note');
  if (!note || !projectId) return;
  try {
    const estimate = await post(`/api/projects/${projectId}/estimate`, {generation_parameters: currentParams()});
    if (estimate.min_seconds == null) note.textContent = `预计生成时间：${estimate.label || '暂无可靠估算'}`;
    else {
      const min = Math.max(1, Math.round(estimate.min_seconds / 60));
      const max = Math.max(min, Math.round(estimate.max_seconds / 60));
      const confidence = estimate.confidence === 'history' ? '高' : '中';
      note.textContent = `预计生成时间：约 ${min}–${max} 分钟 · 依据：${estimate.estimate_basis || '已验证成功记录'} · ${estimate.parameters?.resolution || currentParams().resolution} · ${estimate.parameters?.duration || currentParams().duration}秒 · ${estimate.parameters?.steps || currentParams().steps || 50}步 · 置信度：${confidence}`;
    }
  } catch (_) { note.textContent = '预计生成时间：正在估算'; }
}

function renderOutputDirectory() {
  const el = document.getElementById('output-directory');
  if (el) el.textContent = project?.output_directory || '默认产品目录';
}

function refUrl(ref) { return ref && ref.preview_ready ? ref.preview_url : null; }
function renderRefs() {
  const currentId = (study && study.current_reference_asset_id) || (project && project.current_reference_asset_id);
  selectedRef = refs.find((r) => r.id === currentId)
    || refs.find((r) => r.state === 'PENDING')
    || null;
  const state = document.getElementById('reference-state');
  if (!selectedRef) {
    state.textContent = '未上传'; state.className = 'badge state';
    document.getElementById('reference-preview').innerHTML = '拖拽图片到这里，或点击选择';
    document.getElementById('refs').textContent = '';
    document.getElementById('upload-btn').disabled = !pendingFile;
    return;
  }
  const img = refUrl(selectedRef);
  document.getElementById('reference-preview').innerHTML = img
    ? `<img class="reference-image" src="${esc(img)}" alt="当前参考图">`
    : `<span>${esc(selectedRef.filename)}</span>`;
  document.getElementById('replace-ref-btn').style.display = 'inline-flex';
  document.getElementById('refs').textContent = `${selectedRef.filename} · ${selectedRef.sha256 ? selectedRef.sha256.slice(0, 12) : 'asset'}`;
  const approved = selectedRef.state === 'APPROVED';
  state.textContent = approved ? '参考图已批准 ✓' : '待审批';
  state.className = `badge ${approved ? 'done' : 'warn'}`;
  document.getElementById('upload-btn').disabled = true;
  showViewportRef(selectedRef);
}

function showViewportRef(ref) {
  const url = refUrl(ref);
  document.getElementById('v-body').innerHTML = url
    ? `<img class="preview" src="${esc(url)}" alt="当前参考图">`
    : `<div class="v-empty">${esc(ref.filename)}<br><span class="small">预览暂不可用</span></div>`;
  document.getElementById('v-mode-chip').textContent = ref.state === 'APPROVED' ? '参考图已批准 ✓' : '等待参考图审批';
}

function previewPending(file) {
  pendingFile = file;
  const url = URL.createObjectURL(file);
  document.getElementById('reference-preview').innerHTML = `<img class="reference-image" src="${url}" alt="待上传参考图">`;
  document.getElementById('upload-btn').disabled = false;
  document.getElementById('reference-state').textContent = '待上传';
  document.getElementById('reference-state').className = 'badge warn';
}

async function uploadPending() {
  if (!pendingFile) return;
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const result = await post(`/api/projects/${projectId}/references/upload-approve`, {
        filename: pendingFile.name, role: 'first_frame',
        data_base64: String(reader.result).split(',')[1],
      });
      pendingFile = null; clearErr();
      project = result.project;
      study = result.study;
      refs = (await get(`/api/projects/${projectId}`)).references || [];
      intent = null; prompt = null;
      renderRefs(); renderHeader(); updateGate(); schedulePromptRefresh(80);
    } catch (e) { showErr(e.message); }
  };
  reader.readAsDataURL(pendingFile);
}

function renderPrompt() {
  const card = document.getElementById('prompt-skill-card');
  const details = document.getElementById('prompt-details');
  if (!prompt) { card.style.display = 'none'; details.style.display = 'none'; return; }
  const mode = prompt.engine_mode || 'OFFLINE_COMPILER';
  const reasoning = (mode === 'TEXT_REASONING_H3' || mode === 'MULTIMODAL_H3')
    && prompt.skill_invoked === true && prompt.invocation_result === 'PASS';
  const offline = mode === 'OFFLINE_COMPILER' && prompt.validator_result && prompt.validator_result.pass;
  const official = reasoning;
  const current = !!(study && study.prompt_current && official && prompt.workflow === currentWorkflow());
  card.style.display = 'block';
  card.innerHTML = current
    ? (mode === 'MULTIMODAL_H3'
      ? '<strong>H3 Skill · 图像理解优化 ✓</strong><span class="muted small">已明确同意并使用当前参考图</span>'
      : '<strong>H3 Skill · AI文本优化 ✓</strong><span class="muted small">已执行可选文本推理 Provider</span>')
    : offline
      ? '<strong>H3 官方格式编译 ✓</strong><span class="muted small">未启用 AI 图像理解 · 离线可用</span>'
      : prompt.fallback
        ? '<strong class="warn-text">AI优化失败，已使用 H3 官方格式编译</strong><span class="muted small">可继续生成，不会伪装成 AI 优化</span>'
        : '<strong class="warn-text">提示词需要重新编译…</strong><span class="muted small">旧提示词不会用于生成</span>';
  details.style.display = 'block';
  const provenance = prompt.provenance || {};
  document.getElementById('prompt-detail-content').innerHTML = `
    <div class="prompt-detail-row"><span>Original Intent</span><span>${esc((intent && intent.natural_language) || '—')}</span></div>
    <div class="prompt-detail-row"><span>Optimized Prompt</span><pre class="prompt">${esc(prompt.prompt || '—')}</pre></div>
    <div class="prompt-detail-row"><span>Video Type</span><span>${esc((VIDEO_TYPES.find(([id]) => id === prompt.workflow) || [null, prompt.workflow])[1])}</span></div>
    <div class="prompt-detail-row"><span>Prompt Engine</span><span class="mono small">${esc(`${mode} · ${prompt.provider || '—'}${prompt.model ? ` · ${prompt.model}` : ''}`)}</span></div>
    <div class="prompt-detail-row"><span>Skill specification</span><span>${esc(prompt.skill_source || '—')} · ${esc(prompt.skill_version || '—')}</span></div>
    <div class="prompt-detail-row"><span>更新时间</span><span>${esc(prompt.completed_at || prompt.generated_at || '—')}</span></div>`;
}

async function refreshPrompt() {
  const requestSerial = ++promptRequestSerial;
  const text = value('intent-text').trim();
  if (!text || !selectedRef || selectedRef.state !== 'APPROVED') {
    prompt = null; renderPrompt(); updateGate(); return;
  }
  try {
    document.getElementById('prompt-skill-card').style.display = 'block';
    document.getElementById('prompt-skill-card').innerHTML = '<strong>正在编译 H3 Prompt…</strong><span class="muted small">离线始终可用；已配置的本地 Provider 可在“自动”模式下使用，云端仅在明确选择并同意后执行</span>';
    intent = await post(`/api/projects/${projectId}/intent`, {natural_language: text});
    intent = await post(`/api/projects/${projectId}/workflow/select`, {workflow: currentWorkflow()});
    prompt = await post(`/api/projects/${projectId}/prompt`, {
      workflow: currentWorkflow(), generation_parameters: currentParams(),
      prompt_engine: value('prompt-engine') || 'AUTO',
      image_consent: !!document.getElementById('prompt-image-consent')?.checked,
    });
    if (requestSerial !== promptRequestSerial) return;
    [project, study] = await Promise.all([get(`/api/projects/${projectId}`), refreshStudy()]);
    clearErr(); renderPrompt(); renderHeader(); updateGate();
  } catch (e) {
    if (requestSerial === promptRequestSerial) {
      prompt = {status: 'FAILED', skill_invoked: false, invocation_result: 'FAILED',
        official_skill_status: 'Prompt Skill 调用失败'};
      renderPrompt(); updateGate(); showErr('Prompt Skill 调用失败：' + e.message);
    }
  }
}

function schedulePromptRefresh(delay = 500) {
  clearTimeout(promptTimer);
  promptTimer = setTimeout(refreshPrompt, delay);
}

function syncViewportParams() {
  document.getElementById('v-params').textContent =
    `${value('param-resolution').replace('x', '×')} · ${value('param-fps')}fps · ${value('param-duration')}s`;
}

function updateGate() {
  const approved = !!(study && study.reference_approved);
  const promptReady = !!(study && study.prompt_current && study.prompt_ready
      && prompt && prompt.workflow === currentWorkflow());
  const risk = document.getElementById('risk-check').checked;
  const button = document.getElementById('generate-btn');
  button.disabled = !(approved && promptReady && risk && study.generate_allowed);
  const note = document.getElementById('gate-note');
  if (!approved) note.textContent = '请先上传并审批参考图';
  else if (!promptReady) note.textContent = '正在生成当前 H3 优化提示词…';
  else if (!risk) note.textContent = '请确认参考图与设置';
  else if (study.gate_reasons && study.gate_reasons.length) note.textContent = study.gate_reasons[0];
  else note.textContent = '准备完成，可以生成';
}

async function selectVideoType() {
  document.getElementById('video-type-help').textContent = TYPE_HELP[currentWorkflow()];
  prompt = null; renderPrompt(); updateGate(); schedulePromptRefresh();
}

function selectQuality() {
  const defaults = QUALITY_DEFAULTS[value('param-quality')];
  document.getElementById('param-resolution').value = defaults.resolution;
  // H3's res_multistep mode is the Draft profile. Auto acceleration stays on
  // the sampler mode that supports it.
  document.getElementById('param-sampler').value =
    value('param-speed') === 'auto' ? 'euler' : defaults.sampler_mode;
  prompt = null; renderPrompt(); syncViewportParams(); updateGate(); schedulePromptRefresh();
}

function selectSpeed() {
  if (value('param-speed') === 'auto' && value('param-sampler') === 'res_multistep') {
    document.getElementById('param-sampler').value = 'euler';
  }
  prompt = null; renderPrompt(); syncViewportParams(); updateGate(); schedulePromptRefresh();
}

async function generate() {
  try {
    const rawSeed = value('param-seed').trim();
    const seed = rawSeed ? parseInt(rawSeed, 10) : Math.floor(Math.random() * 900000000);
    if (!Number.isInteger(seed) || seed < 0) { showErr('Seed 需为非负整数或留空'); return; }
    const params = currentParams(); params.seed = seed;
    await post(`/api/projects/${projectId}/jobs`, {
      seed, risk_reviewed: true, generation_parameters: params,
    });
    location.href = `jobs.html?project=${encodeURIComponent(projectId)}`;
  } catch (e) { showErr(e.message); }
}

async function pollJobs() {
  try {
    const jobs = await get(`/api/projects/${projectId}/jobs`);
    await refreshStudy();
    const active = jobs.find((j) => jobIsActive(j));
    const job = active || jobs[0];
    if (job) {
      const progress = job.progress == null ? null : Math.round(job.progress);
      const pct = progress == null ? 0 : progress;
      const progressBar = document.getElementById('v-progress');
      progressBar.style.width = `${pct}%`;
      progressBar.parentElement.classList.toggle('indeterminate', progress == null);
      document.getElementById('v-progress-label').textContent = progress == null ? '—' : `${progress}%`;
      document.getElementById('v-status').textContent = job.current_stage || stateLabel(job.state);
      document.getElementById('current-job-title').textContent = job.workflow ? '当前建筑视频任务' : job.id;
      document.getElementById('current-job-stage').textContent = job.current_stage || stateLabel(job.state);
      document.getElementById('current-job-progress').textContent = progress == null ? '—' : String(progress) + '%' + (job.step != null && job.total_steps != null ? ' · ' + job.step + '/' + job.total_steps : '');
      document.getElementById('current-job-elapsed').textContent = job.elapsed ? `已用时 ${Math.ceil(job.elapsed)}s` : '—';
      document.getElementById('current-job-eta').textContent = formatJobEta(job);
    }
    renderHeader(); updateGate();
    if (!job || jobIsActive(job)) pollTimer = setTimeout(pollJobs, 2000);
    else { clearTimeout(pollTimer); pollTimer = null; }
  } catch (_) {
    /* the engine status control owns service errors */
    pollTimer = setTimeout(pollJobs, 5000);
  }
}

document.getElementById('choose-ref-btn').addEventListener('click', () => document.getElementById('ref-file').click());
document.getElementById('replace-ref-btn').addEventListener('click', () => document.getElementById('ref-file').click());
document.getElementById('ref-file').addEventListener('change', (e) => { if (e.target.files[0]) previewPending(e.target.files[0]); });
document.getElementById('upload-btn').addEventListener('click', uploadPending);
document.getElementById('reference-dropzone').addEventListener('dragover', (e) => { e.preventDefault(); e.currentTarget.classList.add('drag-over'); });
document.getElementById('reference-dropzone').addEventListener('dragleave', (e) => e.currentTarget.classList.remove('drag-over'));
document.getElementById('reference-dropzone').addEventListener('drop', (e) => { e.preventDefault(); e.currentTarget.classList.remove('drag-over'); if (e.dataTransfer.files[0]) previewPending(e.dataTransfer.files[0]); });
document.getElementById('video-type').addEventListener('change', selectVideoType);
document.getElementById('analyze-btn').addEventListener('click', refreshPrompt);
document.getElementById('intent-text').addEventListener('input', () => {
  prompt = null; renderPrompt(); updateGate(); schedulePromptRefresh();
});
document.getElementById('prompt-engine').addEventListener('change', () => {
  prompt = null; renderPrompt(); updateGate(); schedulePromptRefresh();
});
document.getElementById('generate-btn').addEventListener('click', generate);
document.getElementById('risk-check').addEventListener('change', updateGate);
document.getElementById('param-fps').addEventListener('change', () => { syncViewportParams(); refreshEstimate(); });
document.getElementById('rename-study-btn').addEventListener('click', async () => {
  const name = window.prompt('Study 名称', project?.name || '');
  if (!name || !name.trim()) return;
  try { project = await post(`/api/projects/${projectId}/rename`, {name: name.trim()}); renderHeader(); }
  catch (e) { showErr(e.message); }
});
document.getElementById('choose-output-folder').addEventListener('click', async () => {
  try {
    const picked = await post('/api/system/pick-folder', {});
    if (!picked || picked.cancelled || !picked.path) return;
    project = await patch(`/api/projects/${projectId}`, {output_directory: picked.path});
    renderOutputDirectory();
  } catch (e) { showErr(e.message); }
});
['param-duration','param-resolution','param-aspect','param-sampler','param-steps','param-velocity','param-cache-dit'].forEach((id) => {
  document.getElementById(id).addEventListener('change', () => { prompt = null; renderPrompt(); syncViewportParams(); updateGate(); refreshEstimate(); schedulePromptRefresh(); });
});
document.getElementById('param-quality').addEventListener('change', selectQuality);
document.getElementById('param-speed').addEventListener('change', selectSpeed);
document.getElementById('save-provider-btn')?.addEventListener('click', saveProvider);
document.getElementById('test-provider-btn')?.addEventListener('click', testProvider);
document.getElementById('detect-provider-btn')?.addEventListener('click', detectProvider);

function showHydrationFailure(error) {
  const layout = document.querySelector('.studio-layout');
  if (layout) {
    layout.querySelectorAll('button, input, select, textarea').forEach((el) => { el.disabled = true; });
    layout.style.display = 'none';
  }
  const strip = document.getElementById('current-job-strip');
  if (strip) strip.style.display = 'none';
  showErr(`项目加载失败：${error.message || error}。请重试，或返回项目列表。`);
  errEl.innerHTML += ' <button class="btn small" id="retry-project-load" type="button">重试</button> <a class="btn small" href="index.html">返回项目列表</a>';
  document.getElementById('retry-project-load').addEventListener('click', () => location.reload());
}

loadAll().then(() => {
  const layout = document.querySelector('.studio-layout');
  if (layout) layout.style.display = '';
}).catch(showHydrationFailure);
