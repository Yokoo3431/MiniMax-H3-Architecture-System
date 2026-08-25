// Video Studio Workspace V2 (task-centric, Rhino/Enscape visual language)
const projectId = qs('project');
if (!projectId) location.href = 'index.html';

const errEl = document.getElementById('err');
let project = null;
let catalog = null;
let intent = null;
let prompt = null;
let selectedRef = null;
let study = null;

const WF_LABEL = {
  '01_Exterior_Hero': 'Architecture Presentation',
  '02_Day_Night_Transition': 'Day Night',
  '03_Material_Detail': 'Material Detail',
  '04_Drone_Aerial': 'Drone Reveal',
  '05_Slow_Walkthrough': 'Slow Walkthrough',
};
const CAM_UI_TO_INTERNAL = {
  static: 'static', push: 'slow_push', reveal: 'slow_push',
  walkthrough: 'walkthrough', aerial: 'aerial_reveal',
};
const CAMERA_SUGGEST = {
  static: null,
  push: '01_Exterior_Hero',
  reveal: '01_Exterior_Hero',
  walkthrough: '05_Slow_Walkthrough',
  aerial: '04_Drone_Aerial',
};
const CAM_DEFAULT_BY_WF = {
  '01_Exterior_Hero': 'push',
  '02_Day_Night_Transition': 'static',
  '03_Material_Detail': 'static',
  '04_Drone_Aerial': 'aerial',
  '05_Slow_Walkthrough': 'walkthrough',
};
const PROJECT_STEPS = [
  'CREATED','REFERENCE_PENDING','REFERENCE_APPROVED','INTENT_ANALYSIS',
  'PROMPT_NEEDS_CONFIRMATION','PROMPT_REVIEW','USER_CONFIRM','GPU_RUNNING',
  'QUALITY_CHECK','COMPLETED',
];

function showErr(msg) { errEl.style.display = 'block'; errEl.textContent = msg; }
function clearErr() { errEl.style.display = 'none'; }

async function refreshStudy() {
  study = await get(`/api/projects/${projectId}/study`);
  return study;
}

async function loadAll() {
  try {
    const env = await get('/api/system/environment');
    if (env.overall === 'SETUP_REQUIRED' || env.overall === 'BLOCK') {
      location.href = 'setup.html';
      return;
    }
  } catch (_) { /* fall through to workspace */ }
  const [p, c] = await Promise.all([
    get(`/api/projects/${projectId}`),
    get('/api/catalog'),
  ]);
  project = p;
  catalog = c;
  await refreshStudy();
  renderHeader();
  await renderRefs();
  try { intent = await get(`/api/projects/${projectId}/intent`); } catch (_) { intent = null; }
  try { prompt = await get(`/api/projects/${projectId}/prompt`); } catch (_) { prompt = null; }
  await refreshStudy();
  renderHeader();  // refresh viewport chip once intent/prompt are known
  renderIntent();
  renderParams();
  renderAdvanced();
  updateGate();
  pollJobs();
}

function renderHeader() {
  document.getElementById('task-title').textContent = project.name;
  document.getElementById('task-name').textContent = project.name;
  document.getElementById('task-meta').textContent =
    `项目标签: ${project.project_type} · ${project.building_stage} · 更新 ${project.updated_at}`;
  const badge = document.getElementById('task-state');
  const currentState = (study && study.current_state) || project.state;
  const stateLabel = {
    REFERENCE_PENDING: '等待参考图',
    REFERENCE_APPROVED: '参考图已批准',
    PROMPT_REVIEW: '正在准备 Prompt',
    READY_TO_GENERATE: '可以生成',
    GENERATING: '正在生成',
    COMPLETED: '已完成',
    FAILED: '生成失败',
  }[currentState] || currentState;
  badge.textContent = stateLabel;
  badge.className = 'badge ' + (
    ['COMPLETED','READY_TO_GENERATE','REFERENCE_APPROVED'].includes(currentState) ? 'done'
    : ['FAILED','REFERENCE_REJECTED'].includes(currentState) ? 'err'
    : ['GENERATING','PROMPT_REVIEW'].includes(currentState) ? 'warn' : 'state');
  const idx = PROJECT_STEPS.indexOf((study && study.internal_project_state) || project.state);
  document.getElementById('steps').innerHTML = PROJECT_STEPS
    .map((s, i) => `<span class="step ${i < idx ? 'done' : i === idx ? 'active' : ''}">${s}</span>`).join('');
  document.getElementById('v-wf').textContent =
    'workflow: ' + ((intent && intent.selected_workflow) || '—');
  const chip = document.getElementById('v-mode-chip');
  if (intent && intent.selected_workflow) {
    chip.textContent = `${WF_LABEL[intent.selected_workflow]} · ${intent.selected_workflow}`;
  } else {
    chip.textContent = currentState === 'REFERENCE_PENDING' ? '等待参考图' : currentState;
  }
}

// ------------------------------------------------------------------ //
// Reference
// ------------------------------------------------------------------ //
function refImageUrl(r) {
  return r && r.preview_ready && r.preview_url
    ? r.preview_url : null;
}

async function renderRefs() {
  const box = document.getElementById('refs');
  box.innerHTML = '<div class="small muted">加载中…</div>';
  try {
    const refs = await get(`/api/projects/${projectId}/references`);
    if (!refs.length) { box.innerHTML = '<div class="muted small">尚未上传参考图</div>'; return; }
    selectedRef = refs[refs.length - 1] || refs.find((r) => r.state === 'APPROVED');
    box.innerHTML = refs.map((r) => {
      const qq = (r.quality_card || {}).reference_quality || {};
      const img = refImageUrl(r);
      return `<div class="ref-item" data-ref="${r.id}">
        ${img ? `<img class="thumb" src="${img}" alt="">` : '<div class="thumb" style="display:flex;align-items:center;justify-content:center;color:var(--muted);">no image bytes</div>'}
        <div class="row">
          <strong class="small">${esc(r.filename)}</strong>
          <span class="muted small">${esc(r.role)}</span>
        </div>
        <div class="row">
          <span class="badge ${r.state.toLowerCase()}">${esc(r.state)}</span>
          <span class="q">${esc(qq.resolution || '—')} · ${esc(qq.geometry || '—')} · motion ${esc(qq.motion_risk || '—')}</span>
        </div>
        <div class="acts">
          ${r.state === 'PENDING'
            ? `<button class="btn small ok approve-btn">Approve</button>
               <button class="btn small danger reject-btn">Reject</button>`
            : ''}
          <button class="btn small select-btn">预览</button>
        </div>
      </div>`;
    }).join('');
    box.querySelectorAll('.approve-btn').forEach((b) =>
      b.addEventListener('click', () => actRef(b, 'approve')));
    box.querySelectorAll('.reject-btn').forEach((b) =>
      b.addEventListener('click', () => actRef(b, 'reject')));
    box.querySelectorAll('.select-btn').forEach((b) =>
      b.addEventListener('click', () => {
        const id = b.closest('.ref-item').dataset.ref;
        selectedRef = refs.find((x) => x.id === id);
        showViewportRef(selectedRef);
      }));
    if (selectedRef) showViewportRef(selectedRef);
  } catch (e) { showErr(e.message); }
}

function showViewportRef(r) {
  const body = document.getElementById('v-body');
  const img = refImageUrl(r);
  if (img) {
    body.innerHTML = `<img class="preview" src="${img}" alt="">`;
  } else {
    body.innerHTML = `<div class="v-empty">${esc(r.filename)}<br><span class="small">无图片字节（仅元数据）</span></div>`;
  }
  document.getElementById('v-status').textContent =
    `reference: ${r.filename} · ${r.role} · ${r.state}`;
}

async function actRef(btn, action) {
  const refId = btn.closest('.ref-item').dataset.ref;
  try {
    await post(`/api/projects/${projectId}/references/${refId}/${action}`, { reason: '' });
    project = await get(`/api/projects/${projectId}`);
    await refreshStudy();
    renderHeader();
    await renderRefs();
    updateGate();
  } catch (e) { showErr(e.message); }
}

document.getElementById('upload-btn').addEventListener('click', () => {
  const file = document.getElementById('ref-file').files[0];
  if (!file) { showErr('请选择图片文件'); return; }
  const role = document.getElementById('ref-role').value;
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      await post(`/api/projects/${projectId}/references`, {
        filename: file.name, role, data_base64: String(reader.result).split(',')[1],
      });
      clearErr();
      project = await get(`/api/projects/${projectId}`);
      await refreshStudy();
      renderHeader();
      await renderRefs();
      updateGate();
    } catch (e) { showErr(e.message); }
  };
  reader.readAsDataURL(file);
});

// ------------------------------------------------------------------ //
// Intent
// ------------------------------------------------------------------ //
document.getElementById('analyze-btn').addEventListener('click', async () => {
  const text = document.getElementById('intent-text').value.trim();
  if (!text) { showErr('请输入意图描述'); return; }
  try {
    intent = await post(`/api/projects/${projectId}/intent`, { natural_language: text });
    project = await get(`/api/projects/${projectId}`);
    await refreshStudy();
    renderHeader();
    renderIntent();
    renderParams();
    updateGate();
  } catch (e) { showErr(e.message); }
});

function renderIntent() {
  const box = document.getElementById('intent-card');
  const confirmBox = document.getElementById('confirm-box');
  if (!intent) { box.innerHTML = ''; confirmBox.style.display = 'none'; return; }
  const pct = Math.round((intent.confidence || 0) * 100);
  const label = WF_LABEL[intent.selected_workflow] || intent.selected_workflow || '待确认';
  box.innerHTML = `<div class="intent-card">
    <div class="kv"><span class="k">Workflow</span><span><strong>${esc(label)}</strong> <span class="mono muted">${esc(intent.selected_workflow || '')}</span></span></div>
    <div class="kv"><span class="k">Confidence</span><span>${pct}%</span></div>
    <div class="kv"><span class="k">Reason</span><span class="small">${esc(intent.reason)}</span></div>
    <div class="kv"><span class="k">Need Confirmation</span><span>${intent.requires_user_confirmation ? 'YES' : 'NO'}</span></div>
  </div>`;
  confirmBox.style.display = intent.requires_user_confirmation ? 'block' : 'none';
  if (intent.requires_user_confirmation) {
    const sel = document.getElementById('wf-candidates');
    sel.innerHTML = (intent.candidate_workflows || [])
      .map((w) => `<option value="${esc(w)}">${esc(WF_LABEL[w] || w)} (${esc(w)})</option>`).join('');
  }
}

document.getElementById('confirm-btn').addEventListener('click', async () => {
  try {
    intent = await post(`/api/projects/${projectId}/workflow/confirm`, {
      workflow: document.getElementById('wf-candidates').value,
    });
    project = await get(`/api/projects/${projectId}`);
    await refreshStudy();
    renderHeader();
    renderIntent();
    renderParams();
    updateGate();
  } catch (e) { showErr(e.message); }
});

// ------------------------------------------------------------------ //
// Generation Control (parameters + workflow)
// ------------------------------------------------------------------ //
function renderParams() {
  const shelf = document.getElementById('param-shelf');
  if (!intent || intent.requires_user_confirmation) { shelf.style.display = 'none'; return; }
  shelf.style.display = 'block';
  const names = Object.keys(catalog.workflows || {});
  const current = intent.selected_workflow || names[0];
  const wfSelect = document.getElementById('wf-select');
  wfSelect.innerHTML = names.map((n) =>
    `<option value="${esc(n)}" ${n === current ? 'selected' : ''}>${esc(WF_LABEL[n] || n)} (${esc(n)})</option>`).join('');
  renderWorkflowMeta(current);

  // camera segmented (default from intent workflow)
  const camDefault = CAM_DEFAULT_BY_WF[current] || 'push';
  document.querySelectorAll('#camera-seg button').forEach((b) => {
    b.classList.toggle('on', b.dataset.cam === camDefault);
  });
  updateCameraHint(camDefault);
  syncViewportParams();

  if (prompt && prompt.workflow === current) {
    document.getElementById('prompt-preview').textContent = prompt.prompt;
  } else if (prompt && prompt.workflow !== current) {
    document.getElementById('prompt-preview').textContent = '工作流已变更，需重新生成 Prompt 预览。';
  } else {
    document.getElementById('prompt-preview').textContent = '参数已就绪；点击“生成 Prompt 预览”（官方 Skill 只读生成）。';
  }
  get(`/api/projects/${projectId}/references`).then((refs) => {
    const approved = refs.filter((r) => r.state === 'APPROVED');
    document.getElementById('risk-text').innerHTML = approved.length
      ? approved.map((r) => {
          const q = (r.quality_card || {}).reference_quality || {};
          return `<div>${esc(r.filename)} — resolution ${esc(q.resolution || '—')} · geometry ${esc(q.geometry || '—')} · motion risk ${esc(q.motion_risk || '—')}</div>`;
        }).join('')
      : '参考图未批准前无法生成。';
  }).catch(showErr);
}

function renderWorkflowMeta(name) {
  const wf = (catalog.workflows || {})[name] || {};
  document.getElementById('wf-meta').textContent =
    `mode: ${wf.official_skill_mode || '—'} · 冻结工作流，不可编辑`;
}

document.getElementById('wf-select').addEventListener('change', async (e) => {
  try {
    intent = await post(`/api/projects/${projectId}/workflow/select`, {
      workflow: e.target.value,
    });
    prompt = null;
    project = await get(`/api/projects/${projectId}`);
    await refreshStudy();
    renderHeader();
    renderIntent();
    renderParams();
    renderAdvanced();
    updateGate();
  } catch (err) { showErr(err.message); }
});

document.querySelectorAll('#camera-seg button').forEach((b) =>
  b.addEventListener('click', () => {
    document.querySelectorAll('#camera-seg button').forEach((x) => x.classList.remove('on'));
    b.classList.add('on');
    updateCameraHint(b.dataset.cam);
  }));

['param-duration', 'param-resolution', 'param-fps', 'param-quality']
  .forEach((id) => document.getElementById(id).addEventListener('change', syncViewportParams));

function syncViewportParams() {
  document.getElementById('v-params').textContent =
    `${document.getElementById('param-resolution').value.replace('×', 'x')} · ` +
    `${document.getElementById('param-fps').value}fps · ` +
    `${document.getElementById('param-duration').value}`;
}

function updateCameraHint(cam) {
  const suggest = CAMERA_SUGGEST[cam];
  document.getElementById('cam-hint').textContent = suggest
    ? `建议工作流: ${WF_LABEL[suggest]} (${suggest}) — 显式选择优先`
    : '静态机位：结合意图选择工作流（材质→03 / 日夜→02）';
}

// ------------------------------------------------------------------ //
// Gate + generate
// ------------------------------------------------------------------ //
function updateGate() {
  const approved = !!(study && study.reference_approved);
  const intentConfirmed = !!(study && study.intent_analysis &&
    !study.intent_analysis.requires_user_confirmation);
  const promptReady = !!(study && study.prompt_ready && prompt &&
    prompt.workflow === document.getElementById('wf-select').value);
  const riskChecked = document.getElementById('risk-check').checked;

  const previewBtn = document.getElementById('preview-btn');
  previewBtn.disabled = !(approved && intentConfirmed && !promptReady);
  previewBtn.textContent = promptReady ? 'Prompt 已生成' : '生成 Prompt 预览';
  const generateBtn = document.getElementById('generate-btn');
  generateBtn.disabled = !(study && study.generate_allowed && intentConfirmed &&
    promptReady && riskChecked);

  const note = document.getElementById('gate-note');
  if (study && study.current_state === 'GENERATING') note.textContent = '当前任务正在生成';
  else if (!approved) note.textContent = '等待参考图批准（Rule 1）';
  else if (!intentConfirmed) note.textContent = '等待意图确认';
  else if (!promptReady) note.textContent = '先点击“生成 Prompt 预览”（官方 Skill 只读生成）';
  else if (study && study.current_state === 'COMPLETED') note.textContent = '本任务已完成';
  else if (!riskChecked) note.textContent = '请先勾选已审阅风险';
  else if (study && study.gate_reasons && study.gate_reasons.length) {
    note.textContent = study.gate_reasons[0];
  } else note.textContent = '';
}

document.getElementById('risk-check').addEventListener('change', updateGate);

document.getElementById('preview-btn').addEventListener('click', async () => {
  try {
    const rec = await post(`/api/projects/${projectId}/prompt`, {
      workflow: document.getElementById('wf-select').value,
    });
    prompt = rec;
    project = await get(`/api/projects/${projectId}`);
    await refreshStudy();
    renderHeader();
    document.getElementById('prompt-preview').textContent = rec.prompt;
    renderAdvanced();
    updateGate();
  } catch (e) { showErr(e.message); }
});

document.getElementById('generate-btn').addEventListener('click', async () => {
  try {
    const seedInput = document.getElementById('param-seed').value.trim();
    const seed = seedInput ? parseInt(seedInput, 10) : Math.floor(Math.random() * 900000000);
    if (!Number.isInteger(seed) || seed < 0) { showErr('Seed 需为正整数或留空'); return; }
    const activeCam = document.querySelector('#camera-seg button.on')?.dataset.cam || 'push';
    const generation_parameters = {
      resolution: document.getElementById('param-resolution').value.replace('×', 'x'),
      fps: parseInt(document.getElementById('param-fps').value, 10),
      duration: parseFloat(document.getElementById('param-duration').value),
      quality: document.getElementById('param-quality').value === 'Diagnostic'
        ? 'diagnostic' : 'production',
    };
    await post(`/api/projects/${projectId}/jobs`, {
      seed,
      risk_reviewed: true,
      generation_parameters,
      camera_motion: CAM_UI_TO_INTERNAL[activeCam] || 'slow_push',
    });
    location.href = `jobs.html?project=${projectId}`;
  } catch (e) { showErr(e.message); }
});

// ------------------------------------------------------------------ //
// Advanced panel (interface only, no real open)
// ------------------------------------------------------------------ //
function renderAdvanced() {
  const info = document.getElementById('adv-info');
  const btn = document.getElementById('open-comfy-btn');
  if (prompt) {
    const approved = selectedRef ? [selectedRef] : [];
    info.innerHTML =
      `<div class="kv"><span class="k">Current Workflow</span><span>${esc(prompt.workflow)}</span></div>
       <div class="kv"><span class="k">Reference</span><span>${esc(approved.map((r) => r.filename).join(', ') || '—')}</span></div>
       <div class="kv"><span class="k">Prompt Hash</span><span class="mono">${esc(prompt.prompt_hash)}</span></div>`;
    btn.disabled = false;
  } else {
    info.innerHTML = '提交 Prompt 后显示：Current Workflow / Reference / Prompt Hash。';
    btn.disabled = true;
  }
}

document.getElementById('open-comfy-btn').addEventListener('click', () => {
  const box = document.getElementById('adv-contract');
  if (!prompt) return;
  const wfFile = {
    '01_Exterior_Hero': 'workflows/1_建筑效果图_ImageToVideo.json',
    '02_Day_Night_Transition': 'workflows/3_建筑夜景灯光变化_NightTransition.json',
    '03_Material_Detail': 'workflows/1_建筑效果图_ImageToVideo.json',
    '04_Drone_Aerial': 'workflows/04_Drone_Aerial_GOLDEN.json',
    '05_Slow_Walkthrough': 'workflows/2_建筑鸟瞰动画_AerialView.json',
  }[prompt.workflow] || '—';
  box.style.display = 'block';
  box.innerHTML =
    `接口设计（不真实打开）:<br>
     GET http://127.0.0.1:8189/?workflow=${esc(wfFile)}<br>
     &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;prompt_hash=${esc(prompt.prompt_hash)}<br>
     <span class="muted">The launcher binds references and the Official Skill prompt to the selected workflow.</span>`;
});

// ------------------------------------------------------------------ //
// Drawers + collapsed prompt preview
// ------------------------------------------------------------------ //
document.getElementById('ref-toggle').addEventListener('click', () => {
  document.getElementById('drawer-reference').classList.toggle('collapsed');
});
document.getElementById('ctl-toggle').addEventListener('click', () => {
  document.getElementById('drawer-control').classList.toggle('collapsed');
});
document.getElementById('prompt-toggle').addEventListener('click', () => {
  document.getElementById('prompt-wrap').classList.toggle('open');
});

// ------------------------------------------------------------------ //
// Viewport progress (mock job polling)
// ------------------------------------------------------------------ //
async function pollJobs() {
  try {
    const jobs = await get(`/api/projects/${projectId}/jobs`);
    await refreshStudy();
    const running = jobs.find((j) => !['COMPLETED','FAILED','GPU_FAILED','CANCELLED'].includes(j.state));
    if (running) {
      const stageIdx = ['PREPARING','LOADING_MODEL','SAMPLING','ENCODING','EXPORTING','COMPLETED'].indexOf(running.state);
      const pct = Math.min(100, Math.round((Math.max(0, stageIdx) / 5) * 100));
      document.getElementById('v-progress').style.width = pct + '%';
      document.getElementById('v-status').textContent =
        `job ${running.id} · ${running.state} · ${pct}%`;
      setTimeout(pollJobs, 2000);
    } else if (jobs.some((j) => j.state === 'COMPLETED')) {
      document.getElementById('v-progress').style.width = '100%';
      document.getElementById('v-status').textContent = 'status: recent task COMPLETED';
    } else {
      document.getElementById('v-status').textContent =
        study && study.last_job_status === 'GPU_FAILED'
          ? '上次任务失败；当前 Study 已恢复为可重新生成'
          : 'status: ' + ((study && study.current_state) || project.state);
    }
  } catch (_) { /* poll quietly */ }
}

loadAll().catch(showErr);
