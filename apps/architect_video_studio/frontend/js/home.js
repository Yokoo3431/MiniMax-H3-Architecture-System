// Home V2: Recent Tasks + New Video (project = auxiliary tag only)
const tasksEl = document.getElementById('tasks');
const errEl = document.getElementById('err');

function showErr(msg) { errEl.style.display = 'block'; errEl.textContent = msg; }

const WF_LABEL = {
  '01_Exterior_Hero': 'Architecture Presentation',
  '02_Day_Night_Transition': 'Day Night',
  '03_Material_Detail': 'Material Detail',
  '04_Drone_Aerial': 'Drone Reveal',
  '05_Slow_Walkthrough': 'Slow Walkthrough',
};

function stateBadge(state) {
  const cls = ['COMPLETED'].includes(state) ? 'done'
    : ['GPU_FAILED', 'QUALITY_FAILED', 'REFERENCE_REJECTED'].includes(state) ? 'err'
    : ['GPU_RUNNING', 'QUALITY_CHECK'].includes(state) ? 'warn' : 'state';
  return `<span class="badge ${cls}">${esc(state)}</span>`;
}

async function loadTasks() {
  try {
    const projects = await get('/api/projects');
    const rows = [];
    for (const p of projects) {
      let intent = null;
      let prompt = null;
      try { intent = await get(`/api/projects/${p.id}/intent`); } catch (_) {}
      try { prompt = await get(`/api/projects/${p.id}/prompt`); } catch (_) {}
      rows.push({ p, intent, prompt });
    }
    rows.sort((a, b) => (b.p.updated_at || '').localeCompare(a.p.updated_at || ''));
    tasksEl.innerHTML = rows.length
      ? rows.map(({ p, intent, prompt }) => {
          const wf = (intent && intent.selected_workflow) || (prompt && prompt.workflow) || null;
          return `
          <div class="task-card" onclick="location.href='workspace.html?project=${esc(p.id)}'">
            <div class="ttl">
              <span>${esc(p.name)}</span>
              ${stateBadge(p.state)}
            </div>
            <div class="tags">
              ${wf ? `<span class="tag">${esc(WF_LABEL[wf] || wf)}</span>` : '<span class="tag">未选工作流</span>'}
            </div>
            <div class="foot">
              <span>${esc(p.updated_at)}</span>
              ${prompt ? `<span class="mono">#${esc(prompt.prompt_hash.slice(0, 8))}</span>` : ''}
            </div>
          </div>`;
        }).join('')
      : '<div class="muted">还没有 Study，点击 "+ New Study" 开始。</div>';
  } catch (e) { showErr(e.message); }
}

async function checkSystem() {
  try {
    const env = await get('/api/system/environment');
    const el = document.getElementById('sys-status');
    el.innerHTML = env.overall === 'READY'
      ? '<span class="ok">System Ready</span>'
      : `<span class="${env.overall === 'BLOCK' ? 'err' : 'warn'}">System ${esc(env.overall)} — 请打开 Environment Center</span>`;
    if (env.overall === 'SETUP_REQUIRED' || env.overall === 'BLOCK') {
      location.href = 'setup.html';
    }
  } catch (_) { /* keep silent; page still usable */ }
}

document.getElementById('new-video-btn').addEventListener('click', () => {
  document.getElementById('new-task-box').style.display = 'block';
});
document.getElementById('task-cancel-btn').addEventListener('click', () => {
  document.getElementById('new-task-box').style.display = 'none';
});
document.getElementById('task-create-btn').addEventListener('click', async () => {
  const title = document.getElementById('task-title').value.trim() || '未命名 Study';
  try {
    const p = await post('/api/projects', {
      name: title,
      project_type: document.getElementById('task-project-type').value,
      building_stage: document.getElementById('task-stage').value,
    });
    location.href = `workspace.html?project=${p.id}`;
  } catch (e) { showErr(e.message); }
});

loadTasks();
checkSystem();
