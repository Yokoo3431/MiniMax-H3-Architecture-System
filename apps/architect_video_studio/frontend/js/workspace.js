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
let guideFrames = [];
let guideCapabilities = null;
let guideResolution = null;
let pendingGuideFile = null;
const pendingA6Files = Object.create(null);
let guideResolveSerial = 0;
let selectedRef = null;
let pendingFile = null;
const pendingRoleFiles = {first_frame: null, last_frame: null};
const pendingRoleUrls = {first_frame: null, last_frame: null};
let pollTimer = null;
let promptTimer = null;
let promptRequestSerial = 0;
let providerCatalog = [];
let latestJob = null;
let capabilities = null;
let director = null;
let directorJobs = [];
let longFormQueues = [];
let longFormModes = Object.create(null);
let directorRequestBusy = false;
let selectedDirectorShotId = null;

const VIDEO_TYPES = [
  ['01_Exterior_Hero', 'Exterior Hero'],
  ['02_Day_Night_Transition', 'Day / Night Transition'],
  ['03_Material_Detail', 'Material Detail'],
  ['04_Drone_Aerial', 'Drone Aerial'],
  ['05_Slow_Walkthrough', 'Slow Walkthrough'],
];
const A6_IMAGE_ROLES = [
  ['identity_reference', '建筑身份', '保持建筑主体、体量与辨识特征'],
  ['style_reference', '风格参考', '仅提供风格方向，不覆盖建筑身份'],
  ['material_reference', '材质参考', '仅提供材料与表面质感线索'],
  ['site_reference', '场地参考', '提供场地与环境关系线索'],
];
const TYPE_HELP = {
  '01_Exterior_Hero': '建筑外观主镜头，适合入口、立面与整体空间展示。',
  '02_Day_Night_Transition': '日夜与灯光氛围变化，适合表现时间和照明设计。',
  '03_Material_Detail': '材质与细部镜头，适合墙面、节点和构造质感。',
  '04_Drone_Aerial': '航拍与总图展示，适合建筑群、景观和场地关系。',
  '05_Slow_Walkthrough': '人视缓慢漫游，适合室内空间与动线体验。',
};
const STATE_LABELS = {
  NO_REFERENCE: '等待参考图', REFERENCE_PENDING_APPROVAL: '等待审批', READY_TO_CONFIGURE: '准备配置',
  CREATED: '准备中', REFERENCE_PENDING: '等待参考图', REFERENCE_APPROVED: '准备中',
  PROMPT_REVIEW: '准备中', PROMPT_NEEDS_CONFIRMATION: '准备中', USER_CONFIRM: '可以生成',
  GPU_RUNNING: '生成中', QUALITY_CHECK: '整理输出', QUEUED: '排队中', SUBMITTED: '已提交',
  RUNNING: '运行中', GENERATING: '生成中', RECONCILING: '整理输出', COMPLETED: '已完成',
  FAILED: '生成失败', GPU_FAILED: '生成失败', CANCELLED: '已取消', SUBMISSION_LOST: '提交未确认',
  READY_TO_GENERATE: '可以生成',
};

function showErr(msg) { errEl.style.display = 'block'; errEl.textContent = msg; }
function clearErr() { errEl.style.display = 'none'; errEl.textContent = ''; }
function value(id) { return document.getElementById(id).value; }
function currentWorkflow() { return value('video-type'); }
function currentParams() {
  const raw = {
    duration: parseFloat(value('param-duration')),
    quality: value('param-quality'),
    fps: 24,
    delivery_fps: Number(value('param-delivery-fps') || 24),
  };
  const seed = value('param-seed').trim();
  if (seed) raw.seed = parseInt(seed, 10);
  return raw;
}
function stateLabel(state) { return STATE_LABELS[state] || '准备中'; }
function jobIsTerminal(job) { return !!(job && job.is_terminal); }
function jobIsActive(job) { return !!(job && job.is_active); }
// This is a presentation projection of canonical Study/Job fields; it does
// not persist or replace either state model.
function flowState(job = null) {
  if (!study || !study.reference_uploaded) return 'NO_REFERENCE';
  if (!study.reference_approved) return 'REFERENCE_PENDING_APPROVAL';
  if (job && ['QUEUED', 'SUBMITTED', 'RUNNING', 'GENERATING', 'GPU_RUNNING', 'RECONCILING', 'QUALITY_CHECK'].includes(job.state)) return 'GENERATING';
  if (job && job.state === 'COMPLETED') return 'COMPLETED';
  if (job && ['FAILED', 'GPU_FAILED'].includes(job.state)) return 'FAILED';
  if (job && job.state === 'CANCELLED') return 'CANCELLED';
  if (study.prompt_ready && study.generate_allowed) return 'READY_TO_GENERATE';
  return 'READY_TO_CONFIGURE';
}
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
  const etaSeconds = Number(job.eta_seconds);
  const live = Number.isFinite(etaSeconds) && etaSeconds > 0 ? '剩余约 ' + Math.ceil(etaSeconds) + 's' : '';
  if (range) return live ? live + ' · 预计总耗时：' + range : '预计总耗时：' + range;
  return live || '正在估算剩余时间';
}

async function refreshStudy() {
  study = await get(`/api/projects/${projectId}/study`);
  return study;
}

async function loadAll() {
  const [detail, c, system, guides, directorState, longFormState] = await Promise.all([
    get(`/api/projects/${projectId}`), get('/api/catalog'),
    get('/api/capabilities').catch(() => null),
    get(`/api/projects/${projectId}/guide-frames`).catch(() => ({guide_frames: [], capabilities: null})),
    get(`/api/projects/${projectId}/director`).catch(() => ({sequence: null})),
    get(`/api/projects/${projectId}/long-form`).catch(() => ({queues: []})),
  ]);
  capabilities = system?.a4_profiles || null;
  project = detail.project || detail; catalog = c;
  study = detail.study || await refreshStudy();
  refs = detail.references || [];
  guideFrames = guides?.guide_frames || [];
  guideCapabilities = guides?.capabilities || null;
  director = directorState?.sequence || null;
  longFormQueues = longFormState?.queues || [];
  intent = detail.intent || null;
  prompt = detail.prompt || null;
  if (intent && intent.natural_language) document.getElementById('intent-text').value = intent.natural_language;
  await loadProviderCatalog();
  renderHeader(); renderVideoTypes(); renderParams(); renderRefs(); renderGuideFrames(); renderPrompt(); renderOutputDirectory(); renderDirector(); updateGate(); refreshEstimate();
  refreshGuideResolution();
  if (study?.reference_approved
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
  const state = flowState(latestJob);
  badge.textContent = stateLabel(state);
  badge.className = `badge ${['COMPLETED','USER_CONFIRM','READY_TO_GENERATE'].includes(state) ? 'done' : ['FAILED','GPU_FAILED'].includes(state) ? 'err' : state === 'GPU_RUNNING' ? 'warn' : 'state'}`;
}

function renderVideoTypes() {
  const select = document.getElementById('video-type');
  const selected = (intent && intent.selected_workflow) || VIDEO_TYPES[0][0];
  select.innerHTML = VIDEO_TYPES.map(([id, label]) =>
    `<option value="${esc(id)}" ${id === selected ? 'selected' : ''}>${esc(label)}</option>`).join('');
  document.getElementById('video-type-help').textContent = TYPE_HELP[selected];
  renderArchitectureFidelity();
}

function directorShotById(shotId) {
  return director?.shots?.find((shot) => shot.shot_id === shotId) || null;
}

function resolvedShotFrameCount(seconds) {
  const requested = Math.ceil(Number(seconds) * 24 - 1e-9);
  let frames = requested + ((5 - requested) % 17 + 17) % 17;
  while (frames / 24 < Number(seconds)) frames += 17;
  return frames;
}

function newDirectorShot(title = '新镜头') {
  const shotId = `shot-${(globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`).replaceAll('-', '').slice(0, 16)}`;
  return {
    shot_id: shotId, ordinal: director?.shots?.length || 0, title,
    duration_seconds: 4, camera_intent: 'static',
    camera_intent_type: 'PROMPT_CAMERA_INTENT',
    composition_intent: '',
    preservation_intent: '保持建筑主体、体量、轮廓与场地关系稳定，不新增或重构建筑元素。',
    action_intent: '', reference_asset_ids: (prompt?.reference_bindings || []).map((item) => item.asset_id),
    guide_asset_ids: (project?.guide_frames || []).map((item) => item.guide_id),
    audio_intent: '', generation_settings: {quality: 'NATIVE_HIGH', fps: 24},
    runtime_requirement: 'production', prompt_fragment: '', compiled_fragment: '',
    lineage: null, last_job_id: null,
  };
}

function renderDirector() {
  const sequence = director;
  const summary = document.getElementById('director-summary-state');
  const createButton = document.getElementById('director-create-btn');
  const addButton = document.getElementById('director-add-shot-btn');
  const saveButton = document.getElementById('director-save-btn');
  const shotList = document.getElementById('director-shot-list');
  const empty = document.getElementById('director-empty');
  const footer = document.getElementById('director-footer');
  const title = document.getElementById('director-title');
  const revision = document.getElementById('director-revision');
  const select = document.getElementById('director-shot-select');
  if (!summary || !shotList) return;
  const shots = sequence?.shots || [];
  summary.textContent = sequence ? `${shots.length} 镜头 · R${sequence.revision}` : '未创建序列';
  createButton.hidden = !!sequence;
  addButton.hidden = !sequence;
  saveButton.hidden = !sequence;
  footer.hidden = !sequence;
  empty.hidden = !!sequence && shots.length > 0;
  title.disabled = !sequence;
  if (!sequence) {
    shotList.innerHTML = '';
    revision.textContent = 'Studio 独立保存；不会改写现有 Prompt/Job';
    select.innerHTML = '';
    return;
  }
  title.value = sequence.title || '建筑分镜';
  revision.textContent = `序列修订 R${sequence.revision} · ${shots.length} 个独立镜头 Job`;
  const cameraOptions = [
    ['static', '固定镜头'], ['slow_push', '缓慢推进'], ['pull_back', '缓慢拉远'],
    ['orbit', '环绕'], ['pan', '水平摇镜'], ['tilt', '垂直摇镜'],
    ['crane_elevate', '升降揭示'], ['descending_aerial', '下降航拍'],
    ['dolly_lateral', '横向移动'], ['approach', '接近建筑'], ['reveal', '逐步揭示'],
    ['controlled_drone', '平稳无人机镜头'],
  ];
  let timelineOffset = 0;
  const cards = shots.map((shot, index) => {
    const job = directorJobs.find((item) => item.id === shot.last_job_id);
    const duration = Number(shot.duration_seconds || 4);
    const frames = resolvedShotFrameCount(duration);
    const effective = frames / 24;
    const locked = !!shot.last_job_id;
    const refCount = (shot.reference_asset_ids || []).length;
    const guideCount = (shot.guide_asset_ids || []).length;
    const video = job?.state === 'COMPLETED'
      ? `<video class="director-result" controls preload="metadata" src="/api/jobs/${encodeURIComponent(job.id)}/media" aria-label="${esc(shot.title)} 结果"></video>`
      : '';
    const cameraSelect = cameraOptions.map(([id, label]) =>
      `<option value="${id}" ${shot.camera_intent === id ? 'selected' : ''}>${label}</option>`).join('');
    const continuityMode = longFormModes[shot.shot_id] || 'INDEPENDENT';
    const continuitySelect = `<select class="avs-select" data-continuity-mode="${esc(shot.shot_id)}" ${locked ? 'disabled' : ''}>
      <option value="INDEPENDENT" ${continuityMode === 'INDEPENDENT' ? 'selected' : ''}>独立镜头</option>
      <option value="CONTINUE_VISUALLY" ${continuityMode === 'CONTINUE_VISUALLY' ? 'selected' : ''} ${index === 0 ? 'disabled' : ''}>接续上一镜末帧</option>
      <option value="LOCK_PROJECT_IDENTITY" ${continuityMode === 'LOCK_PROJECT_IDENTITY' ? 'selected' : ''}>锁定 Study 身份参考</option>
    </select>`;
    const runtimeState = guideCapabilities?.experimental?.available === true
      && guideCapabilities?.experimental_job_route_enabled === true
      ? '已就绪' : '当前不可用';
    const runtimeSelect = `<select class="avs-select" data-field="runtime_requirement" ${locked ? 'disabled' : ''}>
      <option value="production" ${shot.runtime_requirement === 'production' ? 'selected' : ''} ${guideCount ? 'disabled' : ''}>生产 8189${guideCount ? '（含 guide 时不可用）' : ''}</option>
      <option value="experimental" ${shot.runtime_requirement === 'experimental' ? 'selected' : ''}>隔离实验 8190（${runtimeState}）</option>
    </select>`;
    const status = job ? `${esc(job.state)} · Job ${esc(job.id)}`
      : locked ? `Job ${esc(shot.last_job_id)} · 正在索引` : shot.lineage ? '待提交的定向重拍' : '草稿';
    const retake = job?.state === 'COMPLETED'
      ? `<div class="director-retake-row">
          <label>重拍镜头意图 <select class="avs-select" data-retake-camera="${esc(shot.shot_id)}">${cameraOptions.map(([id, label]) => `<option value="${id}" ${id === shot.camera_intent ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
          <label>重拍原因 <input class="avs-control" data-retake-reason="${esc(shot.shot_id)}" value="保持建筑与参考不变，仅调整镜头意图"></label>
          <button class="spectrum-Button btn ghost director-retake" data-shot-id="${esc(shot.shot_id)}" type="button">创建新 Job 重拍</button>
        </div>` : '';
    const rendered = `<article class="director-shot ${locked ? 'is-executed' : ''}" data-shot-id="${esc(shot.shot_id)}">
      <header class="director-shot-head">
        <span class="director-shot-index">${String(index + 1).padStart(2, '0')}</span>
        <div class="director-shot-heading"><strong>${esc(shot.title || `镜头 ${index + 1}`)}</strong><span class="muted small">序列位置 ${timelineOffset.toFixed(2)}s · ${effective.toFixed(3)}s 实际长度 · ${frames} 帧</span></div>
        <span class="badge state">${status}</span>
        <div class="director-shot-actions">
          <button class="spectrum-Button btn ghost director-move-up" type="button" aria-label="上移镜头" ${index === 0 ? 'disabled' : ''}>↑</button>
          <button class="spectrum-Button btn ghost director-move-down" type="button" aria-label="下移镜头" ${index === shots.length - 1 ? 'disabled' : ''}>↓</button>
          <button class="spectrum-Button btn ghost director-duplicate" type="button">复制</button>
          <button class="spectrum-Button btn ghost director-remove" type="button" ${locked ? 'disabled title="已有 Job 证据的镜头不可删除"' : ''}>移除</button>
        </div>
      </header>
      <div class="director-shot-grid">
        <label>镜头名称<input class="avs-control" data-field="title" value="${esc(shot.title || '')}" ${locked ? 'disabled' : ''}></label>
        <label>时长（秒）<input class="avs-control" data-field="duration_seconds" type="number" min="4" max="15" step="0.1" value="${esc(String(duration))}" ${locked ? 'disabled' : ''}></label>
        <label>相机意图 <select class="avs-select" data-field="camera_intent" ${locked ? 'disabled' : ''}>${cameraSelect}</select></label>
        <label>质量档 <select class="avs-select" data-field="quality" ${locked ? 'disabled' : ''}><option value="NATIVE_HIGH" ${shot.generation_settings?.quality === 'NATIVE_HIGH' ? 'selected' : ''}>NATIVE_HIGH · 1344×768</option><option value="PREVIEW" ${shot.generation_settings?.quality === 'PREVIEW' ? 'selected' : ''}>PREVIEW · 832×480</option></select></label>
        <label class="wide">镜头动作<textarea class="avs-control" data-field="action_intent" rows="2" ${locked ? 'disabled' : ''}>${esc(shot.action_intent || '')}</textarea></label>
        <label>构图意图<input class="avs-control" data-field="composition_intent" value="${esc(shot.composition_intent || '')}" ${locked ? 'disabled' : ''}></label>
        <label>建筑保持<input class="avs-control" data-field="preservation_intent" value="${esc(shot.preservation_intent || '')}" ${locked ? 'disabled' : ''}></label>
        <label class="wide">声音意图（可选）<input class="avs-control" data-field="audio_intent" value="${esc(shot.audio_intent || '')}" ${locked ? 'disabled' : ''}></label>
        <label>本镜头运行时${runtimeSelect}</label>
        <label>长片连续策略${continuitySelect}</label>
      </div>
      <div class="director-binding-line"><span>Study 参考 ${refCount}</span><span>时间线引导 ${guideCount}</span><span>Native H3 24 FPS</span><span>摄像机语义 PROMPT_CAMERA_INTENT</span></div>
      <p class="director-runtime-note">${guideCount
        ? `该镜头含 ${guideCount} 个已配置时间线 guide，必须明确选用隔离 8190（${runtimeState}）；不会回退到生产 8189。`
        : '此镜头使用生产路由；若显式改用实验运行时，将进行独立身份与能力校验。'}</p>
      ${video}${retake}
    </article>`;
    timelineOffset += effective;
    return rendered;
  });
  shotList.innerHTML = cards.join('');
  if (!shots.some((shot) => shot.shot_id === selectedDirectorShotId)) selectedDirectorShotId = shots[0]?.shot_id || null;
  select.innerHTML = shots.map((shot, index) => `<option value="${esc(shot.shot_id)}" ${shot.shot_id === selectedDirectorShotId ? 'selected' : ''}>${String(index + 1).padStart(2, '0')} · ${esc(shot.title || '未命名镜头')}</option>`).join('');
  const queuePanel = document.getElementById('a9-longform');
  if (queuePanel) queuePanel.hidden = !sequence;
  renderLongForm();
}

function renderLongForm() {
  const select = document.getElementById('a9-queue-select');
  const status = document.getElementById('a9-queue-status');
  if (!select || !status) return;
  const previous = select.value || '';
  select.innerHTML = longFormQueues.map((queue) =>
    `<option value="${esc(queue.queue_id)}">${esc(queue.queue_id)} · ${esc(queue.status || 'PENDING')}</option>`
  ).join('');
  if (longFormQueues.some((queue) => queue.queue_id === previous)) select.value = previous;
  const queue = longFormQueues.find((item) => item.queue_id === select.value);
  const resumeButton = document.getElementById('a9-resume-queue');
  const assembleButton = document.getElementById('a9-assemble');
  const generateButton = document.getElementById('director-generate-btn');
  if (!queue) {
    status.textContent = '尚未创建长片队列；逐镜头生成仍由你明确点击，不会后台自动生成。';
    if (resumeButton) resumeButton.disabled = true;
    if (assembleButton) assembleButton.disabled = true;
    if (generateButton) generateButton.textContent = '生成所选镜头';
    return;
  }
  const shotText = (queue.shots || []).map((shot) =>
    `${Number(shot.ordinal) + 1}:${shot.state}${shot.job_id ? `(${shot.job_id})` : ''}`
  ).join(' · ');
  const assembly = queue.assembly || {};
  status.textContent = `${queue.status} · ${shotText || '无镜头'} · ${queue.target?.width || '—'}×${queue.target?.height || '—'} @ ${queue.target?.fps || '—'} FPS${assembly.error_code ? ` · ${assembly.error_code}` : ''}`;
  if (resumeButton) resumeButton.disabled = false;
  if (generateButton) generateButton.textContent = '生成并绑定队列下一镜头';
  if (assembleButton) assembleButton.disabled = !(queue.shots?.length >= 3
    && queue.shots.every((shot) => ['RESULT_READY', 'READY'].includes(shot.state)));
  const video = document.getElementById('a9-result');
  if (video) {
    const url = assembly.status === 'READY' ? assembly.media_url : '';
    video.hidden = !url;
    if (url && video.getAttribute('src') !== url) video.setAttribute('src', url);
  }
}

async function refreshLongFormQueues() {
  const result = await get(`/api/projects/${projectId}/long-form`);
  longFormQueues = result.queues || [];
  renderLongForm();
  return longFormQueues;
}

async function createLongFormQueue() {
  if (!director || directorRequestBusy) return;
  const status = document.getElementById('a9-queue-status');
  try {
    if (!(await saveDirectorSequence())) return;
    const modes = Object.fromEntries((director.shots || []).map((shot) =>
      [shot.shot_id, longFormModes[shot.shot_id] || 'INDEPENDENT']));
    const needsIdentity = Object.values(modes).some((value) =>
      String(value).includes('LOCK_PROJECT_IDENTITY'));
    const identities = needsIdentity ? (prompt?.reference_bindings || []).map((item) => ({
      asset_id: item.asset_id, role: item.role,
      content_sha256: item.sha256,
      approval_state: item.approval_state,
    })) : [];
    const [width, height] = document.getElementById('a9-resolution').value.split('x').map(Number);
    const queue = await post(`/api/projects/${projectId}/long-form`, {
      continuity_modes: modes,
      project_identity_bindings: identities,
      target_resolution: {width, height},
      target_fps: Number(document.getElementById('a9-fps').value),
      audio_policy: document.getElementById('a9-audio').value,
      transition_policy: 'CUT',
    });
    await refreshLongFormQueues();
    document.getElementById('a9-queue-select').value = queue.queue_id;
    renderLongForm();
    if (status) status.textContent = `${queue.status} · 队列已保存；当前续跑决策不会自动提交生成。`;
  } catch (error) {
    if (status) status.textContent = error.message;
    showErr(friendlyError(error, '长片队列创建失败'));
  }
}

async function inspectLongFormResume() {
  const queueId = document.getElementById('a9-queue-select').value;
  const status = document.getElementById('a9-queue-status');
  if (!queueId) return;
  try {
    const result = await post(`/api/projects/${projectId}/long-form/${encodeURIComponent(queueId)}/resume`, {});
    const next = result.resume || {};
    status.textContent = `续跑建议：${next.action || 'UNKNOWN'}${next.shot_id ? ` · ${next.shot_id}` : ''}${next.job_id ? ` · ${next.job_id}` : ''} · 自动提交：否`;
    await refreshLongFormQueues();
  } catch (error) {
    status.textContent = error.message;
    showErr(friendlyError(error, '长片续跑状态读取失败'));
  }
}

async function assembleLongFormQueue() {
  const queueId = document.getElementById('a9-queue-select').value;
  const status = document.getElementById('a9-queue-status');
  const button = document.getElementById('a9-assemble');
  if (!queueId || !button || button.disabled) return;
  button.disabled = true;
  status.textContent = '正在 CPU 装配已有结果；没有 H3 推理…';
  try {
    const result = await post(`/api/projects/${projectId}/long-form/${encodeURIComponent(queueId)}/assemble`, {});
    await refreshLongFormQueues();
    const video = document.getElementById('a9-result');
    if (video && result.assembly?.media_url) {
      video.src = result.assembly.media_url;
      video.hidden = false;
      video.load();
    }
    status.textContent = `装配完成 · ${result.assembly?.media?.width}×${result.assembly?.media?.height} · ${result.assembly?.media?.fps} FPS · ${result.assembly?.media?.duration_seconds}s · 仅复用既有 Job`;
  } catch (error) {
    status.textContent = error.message;
    showErr(friendlyError(error, '长片装配失败；现有镜头 Job 未重跑'));
  } finally {
    button.disabled = false;
    renderLongForm();
  }
}

async function createDirectorSequence() {
  try {
    const result = await post(`/api/projects/${projectId}/director`, {title: '建筑分镜'});
    director = result.sequence;
    selectedDirectorShotId = director.shots?.[0]?.shot_id || null;
    renderDirector();
  } catch (error) { showErr(friendlyError(error, '分镜序列创建失败')); }
}

function readDirectorEditor() {
  if (!director) return;
  director.title = document.getElementById('director-title').value.trim() || '建筑分镜';
  for (const card of document.querySelectorAll('.director-shot')) {
    const shot = directorShotById(card.dataset.shotId);
    if (!shot || shot.last_job_id) continue;
    for (const input of card.querySelectorAll('[data-field]')) {
      const field = input.dataset.field;
      const raw = input.value;
      if (field === 'duration_seconds') shot.duration_seconds = Number(raw);
      else if (field === 'quality') shot.generation_settings.quality = raw;
      else shot[field] = raw;
    }
  }
}

async function saveDirectorSequence() {
  if (!director || directorRequestBusy) return false;
  readDirectorEditor();
  directorRequestBusy = true;
  const status = document.getElementById('director-status');
  if (status) status.textContent = '正在保存分镜…';
  try {
    const result = await put(`/api/projects/${projectId}/director`, {
      expected_revision: director.revision, sequence: director,
    });
    director = result.sequence;
    if (status) status.textContent = `已保存 R${director.revision} · 已执行镜头保持不可变`;
    renderDirector();
    return true;
  } catch (error) {
    if (status) status.textContent = error.message;
    showErr(friendlyError(error, '分镜保存失败'));
    return false;
  } finally { directorRequestBusy = false; }
}

function reorderDirectorShot(shotId, direction) {
  if (!director) return;
  readDirectorEditor();
  const index = director.shots.findIndex((shot) => shot.shot_id === shotId);
  const next = index + direction;
  if (index < 0 || next < 0 || next >= director.shots.length) return;
  [director.shots[index], director.shots[next]] = [director.shots[next], director.shots[index]];
  director.shots.forEach((shot, ordinal) => { shot.ordinal = ordinal; });
  renderDirector();
}

function duplicateDirectorShot(shotId) {
  if (!director) return;
  readDirectorEditor();
  const source = directorShotById(shotId);
  if (!source) return;
  const copy = JSON.parse(JSON.stringify(source));
  copy.shot_id = newDirectorShot().shot_id;
  copy.title = `${source.title || '镜头'} · 副本`;
  copy.last_job_id = null; copy.lineage = null; copy.compiled_fragment = '';
  const index = director.shots.indexOf(source);
  director.shots.splice(index + 1, 0, copy);
  director.shots.forEach((shot, ordinal) => { shot.ordinal = ordinal; });
  selectedDirectorShotId = copy.shot_id;
  renderDirector();
}

function addDirectorShot() {
  readDirectorEditor();
  const shot = newDirectorShot(`镜头 ${(director?.shots?.length || 0) + 1}`);
  director.shots.push(shot);
  selectedDirectorShotId = shot.shot_id;
  renderDirector();
}

function removeDirectorShot(shotId) {
  if (!director) return;
  const shot = directorShotById(shotId);
  if (!shot || shot.last_job_id) return;
  director.shots = director.shots.filter((item) => item.shot_id !== shotId);
  director.shots.forEach((item, ordinal) => { item.ordinal = ordinal; });
  selectedDirectorShotId = director.shots[0]?.shot_id || null;
  renderDirector();
}

function directorGenerationParameters(shot) {
  const params = currentParams();
  params.duration = Number(shot.duration_seconds);
  params.quality = shot.generation_settings?.quality || 'NATIVE_HIGH';
  params.fps = 24; params.delivery_fps = 24;
  const frozenSeed = shot.generation_settings?.seed;
  const rawSeed = value('param-seed').trim();
  params.seed = Number.isInteger(frozenSeed) && frozenSeed >= 0
    ? frozenSeed : (rawSeed ? parseInt(rawSeed, 10) : 42);
  return params;
}

async function compileDirectorShot() {
  if (!director) return;
  const shotId = document.getElementById('director-shot-select').value;
  const shot = directorShotById(shotId);
  if (!shot) return;
  if (!shot.last_job_id && !(await saveDirectorSequence())) return;
  const preview = document.getElementById('director-compile-preview');
  const status = document.getElementById('director-status');
  try {
    const result = await post(`/api/projects/${projectId}/director/compile`, {
      sequence_id: director.sequence_id, sequence_revision: director.revision,
      shot_id: shot.shot_id,
      generation_parameters: directorGenerationParameters(shot),
    });
    preview.textContent = result.compiled_prompt;
    preview.hidden = false;
    status.textContent = `编译通过 · ${result.director_provenance.resolved_frame_count} 帧 · ${result.director_provenance.effective_duration_seconds}s · Prompt SHA ${result.prompt_sha256.slice(0, 12)}… · 未提交任务`;
  } catch (error) {
    status.textContent = error.message;
    showErr(friendlyError(error, '分镜编译预览失败'));
  }
}

async function submitDirectorShot(shot, sequence = director, longFormQueueId = '') {
  const seedValue = directorGenerationParameters(shot).seed;
  if (!Number.isInteger(seedValue) || seedValue < 0) throw new Error('Seed 需为非负整数或留空');
  if (!document.getElementById('risk-check').checked) throw new Error('请先确认参考图与生成设置');
  const runtimeTarget = shot.runtime_requirement || 'production';
  if (!['production', 'experimental'].includes(runtimeTarget)) {
    throw new Error('该镜头的运行时选择无效。');
  }
  if (runtimeTarget === 'production' && (project?.guide_frames || []).length) {
    throw new Error('本 Study 含时间线 guide；请在镜头卡中明确选择隔离实验 8190。');
  }
  const params = directorGenerationParameters(shot);
  const request = {
    seed: seedValue, risk_reviewed: true, generation_parameters: params,
    runtime_target: runtimeTarget,
    director_execution: {
      sequence_id: sequence.sequence_id,
      sequence_revision: sequence.revision,
      shot_id: shot.shot_id,
    },
  };
  if (longFormQueueId) {
    request.long_form_execution = {
      queue_id: longFormQueueId,
      shot_id: shot.shot_id,
    };
  }
  if (runtimeTarget === 'experimental') {
    request.runtime_id = 'experimental-h3-8190';
    request.execution_purpose = 'A7_DIRECTOR_VALIDATION';
  }
  return post(`/api/projects/${projectId}/jobs`, request);
}

async function preflightDirectorShot() {
  if (!director || directorRequestBusy) return;
  const button = document.getElementById('director-preflight-btn');
  const status = document.getElementById('director-status');
  try {
    if (!(await saveDirectorSequence())) return;
    const shot = directorShotById(document.getElementById('director-shot-select').value);
    if (!shot) throw new Error('请先选择一个镜头');
    if ((shot.runtime_requirement || 'production') !== 'experimental') {
      throw new Error('带 guide 的 Director 镜头须先明确选择隔离实验 8190。');
    }
    const seedValue = directorGenerationParameters(shot).seed;
    if (!Number.isInteger(seedValue) || seedValue < 0) throw new Error('Seed 需为非负整数或留空');
    if (!document.getElementById('risk-check').checked) throw new Error('请先确认参考图与设置');
    button.disabled = true;
    button.textContent = '正在进行 CPU 预检…';
    const result = await post(`/api/projects/${projectId}/jobs/preflight`, {
      seed: seedValue, risk_reviewed: true,
      generation_parameters: directorGenerationParameters(shot),
      runtime_target: 'experimental', runtime_id: 'experimental-h3-8190',
      execution_purpose: 'A7_DIRECTOR_VALIDATION',
      director_execution: {sequence_id: director.sequence_id,
        sequence_revision: director.revision, shot_id: shot.shot_id},
    });
    status.textContent = `A7 CPU 预检通过 · ${result.guide_count} guides · 帧 ${result.guide_frame_indexes.join(', ')} · workflow ${result.workflow_sha256.slice(0, 12)}… · ${result.expected_output_prefix} · 未提交 /prompt`;
  } catch (error) {
    status.textContent = error.message;
    showErr(friendlyError(error, 'A7 CPU 预检未通过；未提交 /prompt。'));
  } finally {
    button.disabled = false;
    button.textContent = '仅预检（不生成）';
  }
}

async function generateDirectorShot() {
  if (!director || directorRequestBusy) return;
  const button = document.getElementById('director-generate-btn');
  try {
    if (!(await saveDirectorSequence())) return;
    directorRequestBusy = true;
    if (button) button.disabled = true;
    const shot = directorShotById(document.getElementById('director-shot-select').value);
    if (!shot) throw new Error('请先选择一个镜头');
    const selectedQueueId = document.getElementById('a9-queue-select')?.value || '';
    const queue = longFormQueues.find((item) => item.queue_id === selectedQueueId);
    const queueShot = queue?.shots?.find((item) => item.shot_id === shot.shot_id);
    let queueId = '';
    if (queueShot) {
      if (queueShot.state !== 'PENDING' || queueShot.job_id) {
        throw new Error('该队列镜头已有任务或正在执行；先刷新队列，不会重复提交。');
      }
      queueId = selectedQueueId;
    }
    const created = await submitDirectorShot(shot, director, queueId);
    const job = created && (created.job || created);
    if (job?.id && queueId) {
      await refreshLongFormQueues();
    }
    if (job?.id) location.href = `jobs.html?project=${encodeURIComponent(projectId)}&job=${encodeURIComponent(job.id)}`;
  } catch (error) { showErr(friendlyError(error, 'Director 镜头任务提交失败')); }
  finally {
    directorRequestBusy = false;
    if (button) button.disabled = false;
  }
}

async function createDirectorRetake(shotId, button) {
  if (!director || directorRequestBusy) return;
  const source = directorShotById(shotId);
  if (!source?.last_job_id) return;
  readDirectorEditor();
  const card = button.closest('.director-shot');
  const camera = card.querySelector(`[data-retake-camera="${CSS.escape(shotId)}"]`).value;
  const reason = card.querySelector(`[data-retake-reason="${CSS.escape(shotId)}"]`).value.trim();
  button.disabled = true;
  try {
    const created = await post(`/api/projects/${projectId}/director/shots/${encodeURIComponent(shotId)}/retake`, {
      sequence_id: director.sequence_id, source_job_id: source.last_job_id,
      retake_reason: reason, changes: {camera_intent: camera},
    });
    director = created.sequence;
    selectedDirectorShotId = created.shot.shot_id;
    renderDirector();
    const retake = directorShotById(created.shot.shot_id);
    const result = await submitDirectorShot(retake);
    const job = result && (result.job || result);
    if (job?.id) location.href = `jobs.html?project=${encodeURIComponent(projectId)}&job=${encodeURIComponent(job.id)}`;
  } catch (error) {
    renderDirector();
    showErr(friendlyError(error, '创建或提交重拍失败；原 Job 保持不变'));
  } finally { button.disabled = false; }
}

function renderArchitectureFidelity() {
  const profile = capabilities?.architecture?.[currentWorkflow()];
  const label = profile?.label || TYPE_HELP[currentWorkflow()] || '按视频类型自动选择';
  const el = document.getElementById('architecture-profile');
  if (el) el.textContent = `Automatic · ${label}`;
}

function renderParams() {
  const duration = document.getElementById('param-duration');
  duration.innerHTML = Array.from({length: 12}, (_, i) => i + 4)
    .map((seconds) => `<option value="${seconds}">${seconds} 秒</option>`).join('');
  const saved = (prompt && prompt.generation_parameters) || {};
  if (saved.duration) duration.value = String(saved.duration);
  const qualitySelect = document.getElementById('param-quality');
  const profileList = capabilities?.quality?.profiles;
  if (Array.isArray(profileList) && profileList.length) {
    qualitySelect.innerHTML = profileList.map((profile) => {
      const available = profile.available === true || profile.availability === 'READY';
      const resolution = String(profile.resolution || '').replace('x', '×');
      const label = `${profile.id} · ${resolution}${available ? '' : ' · 暂不可用'}`;
      return `<option value="${esc(profile.id)}" ${available ? '' : 'disabled'} title="${esc(profile.availability_reason || '')}">${esc(label)}</option>`;
    }).join('');
  }
  if (saved.quality) {
    const quality = String(saved.quality).trim().toUpperCase();
    qualitySelect.value = ({HIGH: 'NATIVE_HIGH', DIAGNOSTIC: 'DRAFT', PRODUCTION: 'STANDARD'})[quality] || quality;
  } else qualitySelect.value = 'NATIVE_HIGH';
  const deliveryFps = document.getElementById('param-delivery-fps');
  if (saved.delivery_fps != null) deliveryFps.value = String(saved.delivery_fps);
  if (saved.seed != null) document.getElementById('param-seed').value = String(saved.seed);
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
      note.textContent = `预计生成时间：约 ${min}–${max} 分钟 · 依据：${estimate.estimate_basis || '已验证成功记录'} · ${estimate.parameters?.resolution || '配置解析中'} · ${estimate.parameters?.duration || currentParams().duration}秒 · ${estimate.parameters?.steps || '—'}步 · 置信度：${confidence}`;
    }
  } catch (_) { note.textContent = '预计生成时间：正在估算'; }
}

function renderOutputDirectory() {
  const el = document.getElementById('output-directory');
  if (el) el.textContent = project?.output_directory || '默认产品目录';
}

function refUrl(ref) { return ref && ref.preview_ready ? ref.preview_url : null; }
function renderRefs() {
  renderReferenceBoard();
  const dayNight = currentWorkflow() === '02_Day_Night_Transition';
  document.getElementById('single-reference-controls').hidden = dayNight;
  document.getElementById('day-night-reference-slots').hidden = !dayNight;
  if (dayNight) { renderDayNightRefs(); renderGuideFrames(); return; }
  const currentId = (study && study.current_reference_asset_id) || (project && project.current_reference_asset_id);
  selectedRef = refs.find((r) => r.id === currentId)
    || refs.find((r) => r.state === 'PENDING')
    || null;
  const state = document.getElementById('reference-state');
  if (!selectedRef) {
    state.textContent = '未上传'; state.className = 'badge state';
    document.getElementById('reference-preview').innerHTML = '拖拽图片到这里，或点击选择';
    document.getElementById('refs').textContent = '';
    document.getElementById('choose-ref-btn').style.display = 'inline-flex';
    document.getElementById('choose-ref-btn').textContent = '添加参考图';
    document.getElementById('replace-ref-btn').style.display = 'none';
    document.getElementById('upload-btn').disabled = !pendingFile;
    renderGuideFrames();
    return;
  }
  const img = refUrl(selectedRef);
  document.getElementById('reference-preview').innerHTML = img
    ? `<img class="reference-image" src="${esc(img)}" alt="当前参考图">`
    : `<span>${esc(selectedRef.filename)}</span>`;
  document.getElementById('choose-ref-btn').style.display = 'none';
  document.getElementById('replace-ref-btn').style.display = 'inline-flex';
  document.getElementById('refs').textContent = selectedRef.state !== 'APPROVED'
    ? '待处理参考图'
    : study?.reference_mode === 'Ref2VA'
      ? `A6 ${selectedRef.role} 角色图 · 不作为精确首帧`
      : '当前参考图';
  const approved = selectedRef.state === 'APPROVED';
  state.textContent = approved ? '参考图已批准 ✓' : '待审批';
  state.className = `badge ${approved ? 'done' : 'warn'}`;
  document.getElementById('upload-btn').disabled = true;
  showViewportRef(selectedRef);
  renderGuideFrames();
}

function selectedA6RoleIds() {
  const selected = project?.selected_reference_asset_ids || {};
  return A6_IMAGE_ROLES.map(([role]) => [role, selected[role]])
    .filter(([, assetId]) => !!assetId);
}

function hasExperimentalPurpose() {
  return guideFrames.length > 0 || selectedA6RoleIds().length > 0;
}

function renderReferenceBoard() {
  const root = document.getElementById('a6-reference-list');
  if (!root) return;
  const selected = project?.selected_reference_asset_ids || {};
  const experimental = guideCapabilities?.experimental || {};
  const ref2va = experimental.ref2va || {};
  const routeEnabled = guideCapabilities?.experimental_job_route_enabled === true;
  const experimentPurposeAvailable = hasExperimentalPurpose();
  const dayNight = currentWorkflow() === '02_Day_Night_Transition';
  const capability = document.getElementById('a6-runtime-capability');
  if (capability) {
    if (ref2va.status === 'READY' && routeEnabled) {
      capability.textContent = '隔离实验运行时已报告 Ref2VA 与所需模型能力；A6 仍需显式选中实验运行时。仅明确绑定并获批的 A6 角色图会进入本次 Ref2VA；Study 素材库中的其他图片不会自动加入。';
      capability.dataset.state = 'ready';
    } else if (ref2va.available) {
      capability.textContent = '检测到原生 Ref2VA 节点，但官方 Ref2VA 权重或 Video VAE 未就绪；生成保持关闭。';
      capability.dataset.state = 'unavailable';
    } else {
      capability.textContent = 'Ref2VA 实验能力当前不可用；角色绑定可保存为 Study 元数据，但不会静默转成提示词或普通 I2VA。';
      capability.dataset.state = 'unavailable';
    }
    capability.textContent += ' 当前仅开放图片角色；视频/音频参考导入尚未开放。';
  }
  root.innerHTML = A6_IMAGE_ROLES.map(([role, label, help]) => {
    const currentId = String(selected[role] || '');
    const current = refs.find((item) => String(item.id) === currentId);
    const otherSelections = Object.entries(selected)
      .filter(([otherRole, assetId]) => otherRole !== role && assetId)
      .map(([, assetId]) => refs.find((item) => String(item.id) === String(assetId)))
      .filter(Boolean);
    const usedIdsElsewhere = new Set(otherSelections.map((item) => String(item.id)));
    const hashesUsedElsewhere = new Set(otherSelections
      .filter(Boolean).map((item) => String(item.sha256 || '').toLowerCase()));
    const candidates = refs.filter((item) => item.role === role
      && item.state === 'APPROVED'
      && String(item.media_type || 'image').toLowerCase() === 'image'
      && /^[0-9a-f]{64}$/i.test(String(item.sha256 || ''))
      && (!usedIdsElsewhere.has(String(item.id)) || String(item.id) === currentId)
      && (!hashesUsedElsewhere.has(String(item.sha256).toLowerCase())
          || String(item.id) === currentId));
    const selectedImageRoles = selectedA6RoleIds().map(([selectedRole]) => selectedRole);
    const nativeOrdinal = selectedImageRoles.indexOf(role) + 1;
    const options = ['<option value="">选择本 Study 已审批图片</option>']
      .concat(candidates.map((item) => `<option value="${esc(item.id)}" ${String(item.id) === currentId ? 'selected' : ''}>${esc(item.filename || item.id)}</option>`));
    const preview = current && refUrl(current)
      ? `<img class="a6-role-thumb" src="${esc(refUrl(current))}" alt="${esc(label)}当前图片">`
      : '<span class="guide-thumb-placeholder" aria-hidden="true">图</span>';
    const state = current ? '已批准' : '待绑定';
    const source = current
      ? `来源：当前 Study 素材库 · ${current.filename || '已批准图片'}`
      : '来源：当前 Study 素材库';
    const pendingName = pendingA6Files[role]?.name || '选择图片';
    return `<article class="a6-role-card" data-a6-role="${esc(role)}">
      <div class="a6-role-head">${preview}<div><strong>${esc(label)}</strong><span class="muted small">${esc(state)} · 图片 · ${esc(role)}</span></div>${current ? `<span class="badge state a6-role-order">Picture ${nativeOrdinal}</span>` : ''}</div>
      <p class="muted small">${esc(help)}</p>
      <p class="muted small a6-role-source">${esc(source)}</p>
      <p class="muted small">A6 角色图单张上限 48 MiB；首/末帧和时间线图仍为 20 MiB。</p>
      <label for="a6-existing-${esc(role)}">已批准资产</label>
      <select id="a6-existing-${esc(role)}" class="avs-select a6-asset-select" ${dayNight ? 'disabled' : ''}>${options.join('')}</select>
      <p class="muted small a6-role-candidate-hint">${candidates.length
        ? `可选 ${candidates.length} 张：同 Study、已批准、角色匹配且未与其他角色冲突。`
        : '暂无可直接绑定项：这里只列出同 Study、已批准且角色匹配的图片；已被其他角色使用或内容重复的素材会排除。首帧、末帧和时间线图不会自动转换角色。'}</p>
      <div class="a6-role-actions">
        <button class="spectrum-Button btn small a6-bind" type="button" ${dayNight || !candidates.some((item) => String(item.id) !== currentId) ? 'disabled' : ''}>绑定所选</button>
        <input class="a6-file" type="file" accept="image/png,image/jpeg,image/webp,image/bmp" hidden>
        <button class="spectrum-Button btn small ghost a6-choose-file" type="button" ${dayNight ? 'disabled' : ''}>${esc(pendingName)}</button>
        <button class="spectrum-Button btn small a6-upload" type="button" ${dayNight || !pendingA6Files[role] ? 'disabled' : ''}>上传并审批绑定</button>
        <button class="spectrum-Button btn small ghost a6-remove" type="button" ${!current ? 'disabled' : ''}>移除绑定</button>
      </div>
    </article>`;
  }).join('');
  const validation = document.getElementById('a6-reference-validation');
  if (validation) {
    validation.textContent = dayNight
      ? '当前 Day / Night 工作流保留 first_frame + last_frame 的 FL2VA 契约；请先移除 A6 角色或切换工作流。'
      : selectedA6RoleIds().length
        ? '已选择 A6 参考角色。Ref2VA 本次只使用这些角色图；既有首/末帧不会保留其精确端点语义。若要精确首/末帧，请移除 A6 角色并使用现有 I2VA/FL2VA。'
        : '尚无额外 A6 参考角色；现有 first_frame / last_frame 流程不变。';
  }
}

function renderDayNightRefs() {
  const slots = study?.reference_slots || [];
  const firstSlot = slots.find((item) => item.role === 'first_frame');
  const lastSlot = slots.find((item) => item.role === 'last_frame');
  const firstRef = refs.find((item) => item.id === firstSlot?.asset_id) || null;
  selectedRef = firstRef;
  [['first_frame', firstSlot, 'first-frame'], ['last_frame', lastSlot, 'last-frame']]
    .forEach(([role, slot, prefix]) => {
      const file = pendingRoleFiles[role];
      const preview = document.getElementById(`${prefix}-preview`);
      const badge = document.getElementById(`${prefix}-state`);
      if (file && pendingRoleUrls[role]) {
        preview.innerHTML = `<img class="reference-image" src="${esc(pendingRoleUrls[role])}" alt="待上传${role === 'first_frame' ? '首帧' : '末帧'}">`;
        badge.textContent = '待上传'; badge.className = 'badge warn';
      } else if (slot?.preview_url) {
        preview.innerHTML = `<img class="reference-image" src="${esc(slot.preview_url)}" alt="${role === 'first_frame' ? '已选首帧' : '已选末帧'}">`;
        badge.textContent = slot.approved ? '已批准 ✓' : slot.approval_state === 'PENDING' ? '待审批' : '需重新选择';
        badge.className = `badge ${slot.approved ? 'done' : 'warn'}`;
      } else if (slot?.filename) {
        preview.textContent = slot.filename;
        badge.textContent = slot.approved ? '已批准 ✓ · 预览不可用' : '待处理';
        badge.className = `badge ${slot.approved ? 'done' : 'warn'}`;
      } else {
        preview.textContent = role === 'first_frame' ? '选择开始画面' : '选择结束画面';
        badge.textContent = '未上传'; badge.className = 'badge state';
      }
      document.getElementById(`choose-${prefix}-btn`).hidden = !!slot?.asset_id;
      document.getElementById(`replace-${prefix}-btn`).hidden = !slot?.asset_id;
      document.getElementById(`upload-${prefix}-btn`).disabled = !file;
    });
  const status = document.getElementById('reference-state');
  if (study?.reference_approved) {
    status.textContent = '首帧与末帧已批准 ✓'; status.className = 'badge done';
  } else if (study?.reference_error?.includes('DUPLICATE')) {
    status.textContent = '首末帧重复，请更换'; status.className = 'badge warn';
  } else {
    status.textContent = '需要首帧与末帧'; status.className = 'badge state';
  }
  if (firstRef?.state === 'APPROVED') showViewportRef(firstRef);
  else {
    document.getElementById('v-body').innerHTML = '<div class="v-empty">请分别添加开始画面与结束画面</div>';
    document.getElementById('v-mode-chip').textContent = '日夜过渡 · 等待首末帧';
  }
}

function showViewportRef(ref) {
  const url = refUrl(ref);
  document.getElementById('v-body').innerHTML = url
    ? `<img class="preview" src="${esc(url)}" alt="当前参考图">`
    : `<div class="v-empty">${esc(ref.filename)}<br><span class="small">预览暂不可用</span></div>`;
  document.getElementById('v-mode-chip').textContent = ref.state === 'APPROVED' ? '参考图已批准 ✓' : '等待参考图审批';
}

async function refreshReferenceBoardState() {
  const detail = await get(`/api/projects/${projectId}`);
  project = detail.project || detail;
  study = detail.study || await refreshStudy();
  refs = detail.references || [];
  intent = detail.intent || intent;
  prompt = detail.prompt || null;
  renderRefs(); renderPrompt(); renderHeader(); updateGate();
  if (study?.reference_approved && intent?.natural_language && !study?.prompt_current) {
    schedulePromptRefresh(80);
  }
}

async function bindA6Asset(role, assetId) {
  if (!assetId) { showErr('请选择本 Study 内已审批的同角色图片'); return; }
  try {
    await post(`/api/projects/${projectId}/reference-board/${encodeURIComponent(role)}`,
      {asset_id: assetId});
    clearErr();
    await refreshReferenceBoardState();
  } catch (error) { showErr(friendlyError(error, '参考角色绑定失败。')); }
}

async function removeA6Asset(role) {
  try {
    await api('DELETE', `/api/projects/${projectId}/reference-board/${encodeURIComponent(role)}`);
    clearErr();
    await refreshReferenceBoardState();
  } catch (error) { showErr(friendlyError(error, '参考角色移除失败。')); }
}

async function uploadA6Asset(role) {
  const file = pendingA6Files[role];
  if (!file) { showErr('请先选择一张图片'); return; }
  if (file.size > 48 * 1024 * 1024) {
    showErr('A6 角色图片超过 48 MiB 上限，请选择更小的原图。'); return;
  }
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || '').split(',')[1] || '');
      reader.onerror = () => reject(new Error('无法读取所选图片'));
      reader.readAsDataURL(file);
    });
    if (!dataUrl) throw new Error('无法读取所选图片');
    await post(`/api/projects/${projectId}/references/upload-approve`, {
      filename: file.name, role, data_base64: dataUrl,
    });
    pendingA6Files[role] = null;
    clearErr();
    await refreshReferenceBoardState();
  } catch (error) { showErr(friendlyError(error, '图片上传、审批或绑定失败。')); }
}

function previewPending(file) {
  pendingFile = file;
  const url = URL.createObjectURL(file);
  document.getElementById('reference-preview').innerHTML = `<img class="reference-image" src="${url}" alt="待上传参考图">`;
  document.getElementById('upload-btn').disabled = false;
  document.getElementById('reference-state').textContent = '待上传';
  document.getElementById('reference-state').className = 'badge warn';
}

function renderGuideFrames() {
  const runtime = document.getElementById('guide-runtime-status');
  const production = guideCapabilities?.production;
  const experimental = guideCapabilities?.experimental;
  const experimentRoute = guideCapabilities?.experimental_job_route_enabled === true;
  const experimentPurposeAvailable = hasExperimentalPurpose();
  const canRouteExperiment = !!(experimental?.health === 'PASS'
    && experimentRoute && experimentPurposeAvailable);
  const selector = document.getElementById('runtime-target');
  const experimentOption = selector?.querySelector('option[value="experimental"]');
  if (experimentOption) {
    experimentOption.disabled = !canRouteExperiment;
    experimentOption.textContent = canRouteExperiment
      ? '隔离实验 8190（显式选择）' : '隔离实验 8190（未配置/不可用）';
  }
  if (runtime) {
    const prodText = production?.available
      ? `生产 8189：${production.version} · 原生多帧可用`
      : `生产 8189：${production?.version || '未知'} · 不支持原生多帧`;
    const expText = !experimentPurposeAvailable
      ? '隔离实验 8190：仅限显式 A5 Guide / A6 Ref2VA Job'
      : canRouteExperiment
      ? `隔离实验 8190：${experimental.version} · 可显式选择；A5/A6 能力分别校验`
      : `隔离实验 8190：${experimental?.available ? '节点存在，但 Studio 未配置此 Job 路由' : '未运行或不可用'}`;
    runtime.textContent = `${prodText}；${expText}。有分镜引导时不会自动切换运行时。`;
    runtime.dataset.state = canRouteExperiment ? 'ready' : 'unavailable';
  }

  const select = document.getElementById('guide-asset-select');
  if (select) {
    const approved = refs.filter((item) => item.role === 'timeline_guide'
      && item.state === 'APPROVED');
    const selected = select.value;
    select.innerHTML = approved.length
      ? '<option value="">选择已审批引导图</option>' + approved.map((item) =>
        `<option value="${esc(item.id)}">${esc(item.filename || item.id)}</option>`).join('')
      : '<option value="">先上传一张引导图</option>';
    if (approved.some((item) => item.id === selected)) select.value = selected;
  }
  const count = document.getElementById('guide-count');
  if (count) count.textContent = String(guideFrames.length);
  const approvedGuides = refs.filter((item) => item.role === 'timeline_guide'
    && item.state === 'APPROVED');
  const resolutionById = new Map((guideResolution?.guides || [])
    .map((item) => [item.guide_id, item]));
  const list = document.getElementById('guide-list');
  if (list) {
    list.innerHTML = guideFrames.map((item, index) => {
      const resolved = resolutionById.get(item.guide_id);
      const preview = item.preview_url
        ? `<img src="${esc(item.preview_url)}" alt="分镜引导图 ${index + 1}">`
        : '<span class="guide-thumb-placeholder" aria-hidden="true">图</span>';
      const occupiedByOthers = new Set(guideFrames
        .filter((guide) => guide.guide_id !== item.guide_id)
        .map((guide) => String(guide.asset_id)));
      const replacementAssets = approvedGuides.filter((asset) =>
        String(asset.id) === String(item.asset_id) || !occupiedByOthers.has(String(asset.id)));
      const canReplace = replacementAssets.some((asset) =>
        String(asset.id) !== String(item.asset_id));
      const replacementOptions = replacementAssets.map((asset) =>
        `<option value="${esc(asset.id)}" ${String(asset.id) === String(item.asset_id) ? 'selected' : ''}>${esc(asset.filename || asset.id)}</option>`).join('');
      return `<article class="guide-card" data-guide-id="${esc(item.guide_id)}">
        ${preview}
        <div class="guide-card-meta">
          <strong title="${esc(item.filename || item.asset_id)}">${index + 1}. ${esc(item.filename || item.asset_id)}</strong>
          <label>时间 <input class="guide-time-edit" type="number" min="0" step="0.01" value="${esc(String(item.requested_time_seconds ?? ''))}" aria-label="引导帧时间秒"></label>
          <span class="muted small">${resolved ? `解析帧 ${resolved.resolved_frame_idx} / ${guideResolution.target_frame_count}` : '帧号等待按当前时长预检'}</span>
        </div>
        <div class="guide-card-actions">
          <button class="spectrum-Button btn ghost guide-move-up" type="button" aria-label="上移引导帧" title="上移" ${index === 0 ? 'disabled' : ''}>↑</button>
          <button class="spectrum-Button btn ghost guide-move-down" type="button" aria-label="下移引导帧" title="下移" ${index === guideFrames.length - 1 ? 'disabled' : ''}>↓</button>
          <button class="spectrum-Button btn ghost guide-remove" type="button" aria-label="移除引导帧">移除</button>
        </div>
        <div class="guide-replace-row">
          <select class="avs-select guide-asset-replacement" aria-label="${index + 1}. 替换分镜引导图" ${canReplace ? '' : 'disabled'}>${replacementOptions}</select>
          <button class="spectrum-Button btn ghost guide-replace" type="button" ${canReplace ? '' : 'disabled'}>替换图片</button>
        </div>
        ${canReplace ? '' : '<span class="guide-replace-hint muted small">请先上传并审批另一张未用于时间线的引导图。</span>'}
      </article>`;
    }).join('');
  }
  const validation = document.getElementById('guide-validation');
  if (!guideFrames.length) {
    validation.textContent = '尚未添加引导帧。生产生成仍按现有首/末帧流程。';
    validation.dataset.state = '';
  } else if (!guideResolution) {
    validation.textContent = '正在按当前时长解析目标 H3 帧数…';
    validation.dataset.state = '';
  } else if (!guideResolution.valid) {
    validation.textContent = `时间线未通过：${guideResolution.reason}`;
    validation.dataset.state = 'invalid';
  } else {
    validation.textContent = `${guideFrames.length} 个引导帧通过静态时间线校验 · 目标 ${guideResolution.target_frame_count} 帧 · 原生 24 FPS · ${guideResolution.rounding_policy}`;
    validation.dataset.state = 'ready';
  }
}

async function refreshGuideResolution() {
  const serial = ++guideResolveSerial;
  if (!guideFrames.length) {
    guideResolution = null; renderGuideFrames(); updateGate(); return;
  }
  guideResolution = null;
  renderGuideFrames(); updateGate();
  try {
    const resolved = await post(`/api/projects/${projectId}/guide-frames/resolve`, {
      generation_parameters: currentParams(), workflow_id: currentWorkflow(),
    });
    if (serial !== guideResolveSerial) return;
    guideResolution = resolved;
  } catch (error) {
    if (serial !== guideResolveSerial) return;
    guideResolution = {valid: false, reason: error.message, guides: []};
  }
  renderGuideFrames(); updateGate();
}

async function uploadGuideAsset() {
  const file = pendingGuideFile;
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const result = await post(`/api/projects/${projectId}/references/upload-approve`, {
        filename: file.name, role: 'timeline_guide',
        data_base64: String(reader.result).split(',')[1],
      });
      pendingGuideFile = null;
      document.getElementById('guide-upload-name').textContent = '引导图已通过现有参考图流程审批';
      refs = (await get(`/api/projects/${projectId}`)).references || [];
      guideFrames = (await get(`/api/projects/${projectId}/guide-frames`)).guide_frames || guideFrames;
      const select = document.getElementById('guide-asset-select');
      select.value = result.reference?.id || '';
      clearErr(); renderGuideFrames(); updateGate();
    } catch (error) { showErr(error.message); }
  };
  reader.readAsDataURL(file);
}

async function addGuideFrame() {
  const assetId = value('guide-asset-select');
  const time = Number(value('guide-time-input'));
  if (!assetId) { showErr('请选择一张已审批的分镜引导图'); return; }
  try {
    const result = await post(`/api/projects/${projectId}/guide-frames`, {
      asset_id: assetId, time_seconds: time,
    });
    guideFrames = result.guide_frames || [];
    guideCapabilities = result.capabilities || guideCapabilities;
    guideResolution = null;
    clearErr(); renderGuideFrames(); await refreshGuideResolution();
  } catch (error) { showErr(error.message); }
}

async function updateGuideFrame(guideId, timeSeconds) {
  try {
    const result = await patch(`/api/projects/${projectId}/guide-frames/${encodeURIComponent(guideId)}`, {
      time_seconds: Number(timeSeconds),
    });
    guideFrames = result.guide_frames || [];
    guideCapabilities = result.capabilities || guideCapabilities;
    guideResolution = null; renderGuideFrames(); await refreshGuideResolution();
  } catch (error) { showErr(error.message); renderGuideFrames(); }
}

async function replaceGuideAsset(guideId, assetId) {
  if (!assetId) { showErr('请选择一张已审批且未用于其他时间点的引导图'); return; }
  try {
    const result = await patch(`/api/projects/${projectId}/guide-frames/${encodeURIComponent(guideId)}`, {
      asset_id: assetId,
    });
    guideFrames = result.guide_frames || [];
    guideCapabilities = result.capabilities || guideCapabilities;
    guideResolution = null; clearErr(); renderGuideFrames(); await refreshGuideResolution();
  } catch (error) { showErr(error.message); renderGuideFrames(); }
}

async function removeGuideFrame(guideId) {
  try {
    const result = await api('DELETE', `/api/projects/${projectId}/guide-frames/${encodeURIComponent(guideId)}`);
    guideFrames = result.guide_frames || [];
    guideCapabilities = result.capabilities || guideCapabilities;
    guideResolution = null; renderGuideFrames(); await refreshGuideResolution();
  } catch (error) { showErr(error.message); }
}

async function moveGuideFrame(guideId, direction) {
  const orderedIds = guideFrames.map((item) => item.guide_id);
  const index = orderedIds.indexOf(guideId);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= orderedIds.length) return;
  [orderedIds[index], orderedIds[target]] = [orderedIds[target], orderedIds[index]];
  try {
    const result = await post(`/api/projects/${projectId}/guide-frames/reorder`, {
      guide_ids: orderedIds,
    });
    guideFrames = result.guide_frames || [];
    guideCapabilities = result.capabilities || guideCapabilities;
    guideResolution = null; renderGuideFrames(); await refreshGuideResolution();
  } catch (error) { showErr(error.message); }
}

function previewRolePending(role, file) {
  if (pendingRoleUrls[role]) URL.revokeObjectURL(pendingRoleUrls[role]);
  pendingRoleFiles[role] = file;
  pendingRoleUrls[role] = URL.createObjectURL(file);
  renderDayNightRefs();
  updateGate();
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

async function uploadRolePending(role) {
  const file = pendingRoleFiles[role];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const result = await post(`/api/projects/${projectId}/references/upload-approve`, {
        filename: file.name, role, data_base64: String(reader.result).split(',')[1],
      });
      pendingRoleFiles[role] = null;
      if (pendingRoleUrls[role]) URL.revokeObjectURL(pendingRoleUrls[role]);
      pendingRoleUrls[role] = null;
      clearErr(); project = result.project; study = result.study;
      refs = (await get(`/api/projects/${projectId}`)).references || [];
      intent = null; prompt = null;
      renderRefs(); renderHeader(); updateGate();
      if (study?.reference_approved) schedulePromptRefresh(80);
    } catch (e) { showErr(e.message); }
  };
  reader.readAsDataURL(file);
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
  if (!text || !study?.reference_approved) {
    prompt = null; renderPrompt(); updateGate(); return;
  }
  const selectedQuality = capabilities?.quality?.profiles?.find(
    (item) => item.id === value('param-quality'));
  if (selectedQuality && selectedQuality.available !== true
      && selectedQuality.availability !== 'READY') {
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
  const quality = capabilities?.quality?.profiles?.find(
    (item) => item.id === value('param-quality'));
  const resolution = quality?.resolution || '—';
  document.getElementById('v-params').textContent =
    `${resolution.replace('x', '×')} · 24fps · ${value('param-duration')}s · ${value('param-quality')}`;
}

function updateGate() {
  const approved = !!(study && study.reference_approved);
  const promptReady = !!(study && study.prompt_current && study.prompt_ready
      && prompt && prompt.workflow === currentWorkflow());
  const risk = document.getElementById('risk-check').checked;
  const runtimeTarget = value('runtime-target');
  const selectedA6 = selectedA6RoleIds();
  const requiresRef2VA = selectedA6.length > 0;
  const experimental = guideCapabilities?.experimental;
  const routeEnabled = guideCapabilities?.experimental_job_route_enabled === true;
  const runtimeCapability = runtimeTarget === 'experimental'
    ? guideCapabilities?.experimental
    : guideCapabilities?.production;
  const runtimeReady = runtimeTarget === 'production'
    ? runtimeCapability?.available === true
    : (requiresRef2VA ? experimental?.health === 'PASS'
                      : experimental?.available === true)
      && routeEnabled && (guideFrames.length > 0 || requiresRef2VA);
  const ref2vaReady = experimental?.ref2va?.status === 'READY';
  const button = document.getElementById('generate-btn');
  const preflightButton = document.getElementById('a5-preflight-btn');
  if (preflightButton) {
    preflightButton.hidden = runtimeTarget !== 'experimental'
      || (!guideFrames.length && !requiresRef2VA);
    preflightButton.disabled = true;
  }
  button.disabled = !(approved && promptReady && risk && study.generate_allowed);
  button.setAttribute('aria-describedby', 'gate-note preflight-result');
  button.setAttribute('aria-disabled', String(button.disabled));
  const note = document.getElementById('gate-note');
  if (!study?.reference_uploaded) note.textContent = '请先添加参考图';
  else if (!approved) note.textContent = (study.gate_reasons || [])[0] || '参考图尚未满足当前视频类型的角色与审批要求';
  else {
    if (requiresRef2VA && currentWorkflow() === '02_Day_Night_Transition') {
      note.textContent = 'Day / Night 保持既有 first_frame + last_frame FL2VA 语义；请先移除 A6 角色绑定。';
      button.disabled = true;
      return;
    }
    if (requiresRef2VA && guideFrames.length) {
      note.textContent = '当前不支持将 Ref2VA 多参考与 A5 时间线引导组合；请先移除其中一类。';
      button.disabled = true;
      return;
    }
    if (requiresRef2VA && runtimeTarget !== 'experimental') {
      note.textContent = '已绑定 A6 多参考角色；请显式选择隔离实验 8190。不会回退到生产 8189。';
      button.disabled = true;
      return;
    }
    if (requiresRef2VA && (!runtimeReady || !ref2vaReady)) {
      note.textContent = 'A6 Ref2VA 尚未就绪：需要隔离运行时路由、原生节点、官方 Ref2VA 权重和 Video VAE；不会创建生成任务。';
      button.disabled = true;
      return;
    }
    if (requiresRef2VA) {
      note.textContent = 'A6 Ref2VA 使用已批准的角色参考图；现有首/末帧不作为精确端点条件。可先运行 CPU 实验路由预检。';
    }
    if (runtimeTarget === 'experimental' && !guideFrames.length && !requiresRef2VA) {
      note.textContent = '隔离运行时仅用于显式 A5 Guide 或 A6 Ref2VA 验收；普通视频继续使用生产 8189。';
      button.disabled = true;
      return;
    }
    if (runtimeTarget === 'experimental' && !runtimeReady) {
      note.textContent = '隔离实验运行时未显式配置或不可用；不会回退到生产运行时';
      button.disabled = true;
      return;
    }
    if (runtimeTarget === 'experimental' && !guideFrames.length && !requiresRef2VA) {
      note.textContent = '隔离实验运行时仅用于显式 A5 多帧引导验证；请先添加并批准分镜引导图';
      button.disabled = true;
      return;
    }
    if (guideFrames.length) {
      if (runtimeTarget !== 'experimental') {
        note.textContent = '当前生产 8189 不支持原生分镜引导；请显式选择已启用的隔离 8190，系统不会静默丢弃引导帧';
        button.disabled = true;
        return;
      }
      if (!runtimeReady) {
        note.textContent = '隔离 8190 尚未就绪；引导帧不会被移交给生产 8189';
        button.disabled = true;
        return;
      }
    }
    if (guideFrames.length && (!guideResolution || guideResolution.valid !== true)) {
      note.textContent = guideResolution?.reason
        ? `分镜时间线校验失败：${guideResolution.reason}` : '正在校验分镜引导的目标帧号…';
      button.disabled = true;
      return;
    }
    const quality = capabilities?.quality?.profiles?.find(
      (item) => item.id === value('param-quality'));
    if (quality && quality.available !== true && quality.availability !== 'READY') {
      note.textContent = quality.availability_reason || '当前质量档位尚未通过执行验证';
      button.disabled = true;
      return;
    }
    if (Number(value('param-delivery-fps')) !== 24) {
      note.textContent = '交付 30/48/60 FPS 需要尚未启用的后处理流程';
      button.disabled = true;
      return;
    }
    if (!promptReady) note.textContent = '正在生成当前 H3 优化提示词…';
    else if (!risk) note.textContent = '请确认参考图与设置';
    else if (study.gate_reasons && study.gate_reasons.length) note.textContent = study.gate_reasons[0];
    else note.textContent = '准备完成，可以生成';
  }
  if (preflightButton) {
    const a6PreflightReady = requiresRef2VA && ref2vaReady;
    const a5PreflightReady = guideFrames.length > 0
      && guideResolution?.valid === true;
    preflightButton.disabled = !(runtimeTarget === 'experimental' && runtimeReady
      && approved && promptReady && risk && study?.generate_allowed
      && (a6PreflightReady || a5PreflightReady));
    preflightButton.textContent = '仅验证实验路由（不生成）';
  }
}

async function selectVideoType() {
  document.getElementById('video-type-help').textContent = TYPE_HELP[currentWorkflow()];
  renderArchitectureFidelity();
  renderRefs();
  prompt = null; renderPrompt(); updateGate(); refreshEstimate(); schedulePromptRefresh();
}

function selectQuality() {
  prompt = null; renderPrompt(); syncViewportParams(); updateGate(); refreshEstimate(); schedulePromptRefresh();
}

async function generate() {
  try {
    const rawSeed = value('param-seed').trim();
    const seed = rawSeed ? parseInt(rawSeed, 10) : Math.floor(Math.random() * 900000000);
    if (!Number.isInteger(seed) || seed < 0) { showErr('Seed 需为非负整数或留空'); return; }
    const params = currentParams(); params.seed = seed;
    const runtimeTarget = value('runtime-target');
    const request = {
      seed, risk_reviewed: true, generation_parameters: params,
      runtime_target: runtimeTarget,
    };
    if (runtimeTarget === 'experimental') {
      request.runtime_id = 'experimental-h3-8190';
      request.execution_purpose = selectedA6RoleIds().length
        ? 'A6_REF2VA_VALIDATION' : 'A5_EXPERIMENTAL_VALIDATION';
    }
    const created = await post(`/api/projects/${projectId}/jobs`, request);
    const job = created && (created.job || created);
    const jobQuery = job?.id ? `&job=${encodeURIComponent(job.id)}` : '';
    location.href = `jobs.html?project=${encodeURIComponent(projectId)}${jobQuery}`;
  } catch (e) { showErr(friendlyError(e, '生成任务提交失败，请检查参考图、提示词和设置。')); }
}

async function runExperimentalPreflight() {
  const button = document.getElementById('a5-preflight-btn');
  const resultNote = document.getElementById('preflight-result');
  if (value('runtime-target') !== 'experimental') return;
  const isA6 = selectedA6RoleIds().length > 0;
  button.disabled = true;
  button.textContent = '正在进行 CPU 预检…';
  resultNote.textContent = '正在进行 CPU 预检；不会提交 /prompt。';
  resultNote.hidden = false;
  try {
    const rawSeed = value('param-seed').trim();
    const seed = rawSeed ? parseInt(rawSeed, 10) : 42;
    if (!Number.isInteger(seed) || seed < 0) throw new Error('Seed 需为非负整数');
    const params = currentParams(); params.seed = seed;
    const result = await post(`/api/projects/${projectId}/jobs/preflight`, {
      seed, risk_reviewed: document.getElementById('risk-check').checked,
      generation_parameters: params,
      runtime_target: 'experimental', runtime_id: 'experimental-h3-8190',
      execution_purpose: isA6
        ? 'A6_REF2VA_VALIDATION' : 'A5_EXPERIMENTAL_VALIDATION',
    });
    resultNote.textContent = isA6
      ? `A6 CPU 预检通过 · ${result.ref2va_count} 个角色参考 · workflow ${result.workflow_sha256.slice(0, 12)}…；未提交 /prompt`
      : `A5 CPU 预检通过 · ${result.guide_count} guides · 帧 ${result.guide_frame_indexes.join(', ')} · workflow ${result.workflow_sha256.slice(0, 12)}…；未提交 /prompt`;
  } catch (e) {
    const message = friendlyError(e, '实验 CPU 预检未通过；未提交 /prompt。');
    resultNote.textContent = message;
    resultNote.hidden = false;
    showErr(message);
  } finally {
    button.textContent = '仅验证实验路由（不生成）';
    updateGate();
  }
}

async function pollJobs() {
  try {
    const jobs = await get(`/api/projects/${projectId}/jobs`);
    directorJobs = jobs;
    const directorPanel = document.getElementById('director-panel');
    if (!directorPanel?.contains(document.activeElement)) renderDirector();
    await refreshStudy();
    const active = jobs.find((j) => jobIsActive(j));
    const job = active || jobs[0];
    latestJob = job || null;
    if (job) {
      const progress = job.progress == null ? null : Math.round(job.progress);
      const progressBar = document.getElementById('v-progress');
      if (progress == null) progressBar.style.removeProperty('width');
      else progressBar.style.width = `${Math.max(0, Math.min(100, progress))}%`;
      progressBar.parentElement.classList.toggle('indeterminate', progress == null);
      document.getElementById('v-progress-label').textContent = progress == null ? '—' : `${progress}%`;
      document.getElementById('v-status').textContent = job.current_stage || stateLabel(job.state);
      document.getElementById('current-job-title').textContent = job.workflow ? '当前建筑视频任务' : job.id;
      document.getElementById('current-job-stage').textContent = job.current_stage || stateLabel(job.state);
      document.getElementById('current-job-progress').textContent = progress == null ? '—' : String(progress) + '%' + (job.step != null && job.total_steps != null ? ' · ' + job.step + '/' + job.total_steps : '');
      document.getElementById('current-job-elapsed').textContent = job.elapsed ? `已用时 ${Math.ceil(job.elapsed)}s` : '—';
      document.getElementById('current-job-eta').textContent = formatJobEta(job);
      const outputLink = document.getElementById('current-job-output');
      if (outputLink) {
        const available = job.state === 'COMPLETED' && job.id;
        outputLink.hidden = !available;
        if (available) {
          outputLink.href = `output.html?project=${encodeURIComponent(projectId)}&job=${encodeURIComponent(job.id)}`;
        }
      }
    } else {
      document.getElementById('v-status').textContent = stateLabel(study?.current_state);
      document.getElementById('v-progress-label').textContent = '—';
      document.getElementById('v-progress').style.removeProperty('width');
      document.getElementById('v-progress').parentElement.classList.remove('indeterminate');
      document.getElementById('current-job-title').textContent = '尚无任务';
      document.getElementById('current-job-stage').textContent = stateLabel(study?.current_state);
      document.getElementById('current-job-progress').textContent = '—';
      document.getElementById('current-job-elapsed').textContent = '—';
      document.getElementById('current-job-eta').textContent = '暂无任务';
      const outputLink = document.getElementById('current-job-output');
      if (outputLink) outputLink.hidden = true;
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
[
  ['first_frame', 'first-frame'], ['last_frame', 'last-frame'],
].forEach(([role, prefix]) => {
  document.getElementById(`choose-${prefix}-btn`).addEventListener('click', () =>
    document.getElementById(`${prefix}-file`).click());
  document.getElementById(`replace-${prefix}-btn`).addEventListener('click', () =>
    document.getElementById(`${prefix}-file`).click());
  document.getElementById(`${prefix}-file`).addEventListener('change', (event) => {
    if (event.target.files[0]) previewRolePending(role, event.target.files[0]);
  });
  document.getElementById(`upload-${prefix}-btn`).addEventListener('click', () =>
    uploadRolePending(role));
});
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
document.getElementById('a5-preflight-btn').addEventListener('click', runExperimentalPreflight);
document.getElementById('runtime-target').addEventListener('change', updateGate);
document.getElementById('choose-guide-file-btn').addEventListener('click', () =>
  document.getElementById('guide-file').click());
document.getElementById('guide-file').addEventListener('change', (event) => {
  pendingGuideFile = event.target.files[0] || null;
  document.getElementById('guide-upload-name').textContent = pendingGuideFile
    ? `${pendingGuideFile.name} · 上传后需明确加入时间线` : '单张图片；不会上传到外部服务';
  if (pendingGuideFile) uploadGuideAsset();
});
document.getElementById('add-guide-btn').addEventListener('click', addGuideFrame);
document.getElementById('guide-list').addEventListener('change', (event) => {
  if (!event.target.matches('.guide-time-edit')) return;
  const guideId = event.target.closest('[data-guide-id]')?.dataset.guideId;
  if (guideId) updateGuideFrame(guideId, event.target.value);
});
document.getElementById('guide-list').addEventListener('click', (event) => {
  const button = event.target.closest('.guide-remove');
  const replaceButton = event.target.closest('.guide-replace');
  const card = event.target.closest('[data-guide-id]');
  const guideId = card?.dataset.guideId;
  if (!button && !replaceButton && !event.target.closest('.guide-move-up, .guide-move-down')) return;
  if (!guideId) return;
  if (button) removeGuideFrame(guideId);
  else if (replaceButton) replaceGuideAsset(
    guideId, card.querySelector('.guide-asset-replacement')?.value);
  else if (event.target.closest('.guide-move-up')) moveGuideFrame(guideId, -1);
  else if (event.target.closest('.guide-move-down')) moveGuideFrame(guideId, 1);
});
document.getElementById('a6-reference-list').addEventListener('change', (event) => {
  const card = event.target.closest('[data-a6-role]');
  if (!card) return;
  const role = card.dataset.a6Role;
  if (event.target.matches('.a6-file')) {
    pendingA6Files[role] = event.target.files[0] || null;
    renderReferenceBoard();
  } else if (event.target.matches('.a6-asset-select')) {
    const currentId = String((project?.selected_reference_asset_ids || {})[role] || '');
    card.querySelector('.a6-bind').disabled = !event.target.value
      || event.target.value === currentId
      || currentWorkflow() === '02_Day_Night_Transition';
  }
});
document.getElementById('a6-reference-list').addEventListener('click', (event) => {
  const card = event.target.closest('[data-a6-role]');
  if (!card) return;
  const role = card.dataset.a6Role;
  if (event.target.closest('.a6-choose-file')) card.querySelector('.a6-file').click();
  else if (event.target.closest('.a6-bind')) {
    bindA6Asset(role, card.querySelector('.a6-asset-select')?.value);
  } else if (event.target.closest('.a6-upload')) uploadA6Asset(role);
  else if (event.target.closest('.a6-remove')) removeA6Asset(role);
});
document.getElementById('director-create-btn').addEventListener('click', createDirectorSequence);
document.getElementById('director-add-shot-btn').addEventListener('click', addDirectorShot);
document.getElementById('director-save-btn').addEventListener('click', saveDirectorSequence);
document.getElementById('director-compile-btn').addEventListener('click', compileDirectorShot);
document.getElementById('director-generate-btn').addEventListener('click', generateDirectorShot);
document.getElementById('director-preflight-btn').addEventListener('click', preflightDirectorShot);
document.getElementById('director-title').addEventListener('input', (event) => {
  if (director) director.title = event.target.value;
});
document.getElementById('director-shot-select').addEventListener('change', (event) => {
  selectedDirectorShotId = event.target.value;
});
function syncDirectorField(event) {
  const card = event.target.closest('.director-shot');
  const shot = card && directorShotById(card.dataset.shotId);
  const input = event.target.closest('[data-field]');
  if (!shot || !input || shot.last_job_id) return;
  if (input.dataset.field === 'duration_seconds') shot.duration_seconds = Number(input.value);
  else if (input.dataset.field === 'quality') shot.generation_settings.quality = input.value;
  else shot[input.dataset.field] = input.value;
}
document.getElementById('director-shot-list').addEventListener('input', syncDirectorField);
document.getElementById('director-shot-list').addEventListener('change', (event) => {
  syncDirectorField(event);
  const mode = event.target.closest('[data-continuity-mode]');
  if (mode) longFormModes[mode.dataset.continuityMode] = mode.value;
});
document.getElementById('director-shot-list').addEventListener('click', (event) => {
  const card = event.target.closest('.director-shot');
  const shotId = card?.dataset.shotId;
  if (!shotId) return;
  if (event.target.closest('.director-move-up')) reorderDirectorShot(shotId, -1);
  else if (event.target.closest('.director-move-down')) reorderDirectorShot(shotId, 1);
  else if (event.target.closest('.director-duplicate')) duplicateDirectorShot(shotId);
  else if (event.target.closest('.director-remove')) removeDirectorShot(shotId);
  else if (event.target.closest('.director-retake')) createDirectorRetake(shotId, event.target.closest('.director-retake'));
});
document.getElementById('a9-create-queue').addEventListener('click', createLongFormQueue);
document.getElementById('a9-refresh-queue').addEventListener('click', () => refreshLongFormQueues().catch((error) => showErr(error.message)));
document.getElementById('a9-queue-select').addEventListener('change', renderLongForm);
document.getElementById('a9-resume-queue').addEventListener('click', inspectLongFormResume);
document.getElementById('a9-assemble').addEventListener('click', assembleLongFormQueue);
document.getElementById('risk-check').addEventListener('change', updateGate);
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
['param-duration','param-seed'].forEach((id) => {
  document.getElementById(id).addEventListener('change', () => { prompt = null; renderPrompt(); syncViewportParams(); updateGate(); refreshEstimate(); schedulePromptRefresh(); refreshGuideResolution(); });
});
document.getElementById('param-quality').addEventListener('change', selectQuality);
document.getElementById('param-delivery-fps').addEventListener('change', () => {
  prompt = null; renderPrompt(); updateGate(); refreshEstimate();
});
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
  errEl.innerHTML += ' <button class="spectrum-Button btn small" id="retry-project-load" type="button">重试</button> <a class="btn small" href="index.html">返回项目列表</a>';
  document.getElementById('retry-project-load').addEventListener('click', () => location.reload());
}

loadAll().then(() => {
  const layout = document.querySelector('.studio-layout');
  if (layout) layout.style.display = '';
}).catch(showHydrationFailure);
