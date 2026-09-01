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
  const labels = {
    READY_TO_GENERATE: '可以生成', GENERATING: '正在生成', COMPLETED: '已完成',
    REFERENCE_PENDING: '等待参考图', PROMPT_REVIEW: '准备 Prompt', FAILED: '生成失败',
  };
  const cls = ['COMPLETED', 'READY_TO_GENERATE'].includes(state) ? 'done'
    : ['FAILED', 'REFERENCE_REJECTED'].includes(state) ? 'err'
    : ['GENERATING', 'PROMPT_REVIEW'].includes(state) ? 'warn' : 'state';
  return `<span class="badge ${cls}">${esc(labels[state] || state)}</span>`;
}

async function loadTasks() {
  try {
    const projects = await get('/api/projects');
    const rows = [];
    for (const p of projects) {
      let intent = null;
      let prompt = null;
      let study = null;
      try { intent = await get(`/api/projects/${p.id}/intent`); } catch (_) {}
      try { prompt = await get(`/api/projects/${p.id}/prompt`); } catch (_) {}
      try { study = await get(`/api/projects/${p.id}/study`); } catch (_) {}
      rows.push({ p, intent, prompt, study });
    }
    rows.sort((a, b) => (b.p.updated_at || '').localeCompare(a.p.updated_at || ''));
    tasksEl.innerHTML = rows.length
      ? rows.map(({ p, intent, prompt, study }) => {
          const wf = (intent && intent.selected_workflow) || (prompt && prompt.workflow) || null;
          const displayState = study && study.current_state || p.state;
          return `
          <div class="task-card" onclick="location.href='workspace.html?project=${esc(p.id)}'">
            <div class="ttl">
              <span>${esc(p.name)}</span>
              ${stateBadge(displayState)}
            </div>
            <div class="tags">
              ${wf ? `<span class="tag">${esc(WF_LABEL[wf] || wf)}</span>` : '<span class="tag">未选工作流</span>'}
            </div>
            <div class="foot">
              <span>${esc(p.updated_at)}</span>
              ${prompt ? `<span class="mono">#${esc(prompt.prompt_hash.slice(0, 8))}</span>` : ''}
            </div>
            <div class="task-actions" onclick="event.stopPropagation()">
              <button class="btn small ghost" data-action="rename" data-project="${esc(p.id)}">重命名</button>
              <button class="btn small ghost" data-action="duplicate" data-project="${esc(p.id)}">复制</button>
              <button class="btn small ghost danger" data-action="delete" data-project="${esc(p.id)}">删除</button>
            </div>
          </div>`;
        }).join('')
      : '<div class="muted">还没有 Study，点击 "+ New Study" 开始。</div>';
    tasksEl.querySelectorAll('[data-action]').forEach((button) => {
      button.addEventListener('click', async () => {
        const id = button.dataset.project;
        try {
          if (button.dataset.action === 'rename') {
            const current = projects.find((item) => item.id === id);
            const name = window.prompt('Study 名称', current?.name || '');
            if (!name || !name.trim()) return;
            await post(`/api/projects/${encodeURIComponent(id)}/rename`, {name: name.trim()});
          } else if (button.dataset.action === 'duplicate') {
            await post(`/api/projects/${encodeURIComponent(id)}/duplicate`, {});
          } else if (button.dataset.action === 'delete') {
            const current = projects.find((item) => item.id === id);
            const activeJob = (await get(`/api/projects/${encodeURIComponent(id)}`)).current_job;
            if (activeJob) {
              if (!window.confirm('该项目仍有正在执行的任务。\n确定取消任务并删除 Study？')) return;
              await post(`/api/jobs/${encodeURIComponent(activeJob.id)}/cancel`, {});
            }
            if (!window.confirm(`删除此 Study「${current?.name || ''}」？`)) return;
            const keepOutputs = window.confirm('保留已生成视频？\n确定=保留输出；取消=同时删除已生成视频。');
            const response = await fetch(`/api/projects/${encodeURIComponent(id)}`, {method: 'DELETE', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({confirm: true, delete_outputs: !keepOutputs})});
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || '删除失败');
          }
          await loadTasks();
        } catch (e) { showErr(e.message); }
      });
    });
  } catch (e) { showErr(e.message); }
}

async function checkSystem() {
  try {
    const env = await get('/api/system/environment');
    const el = document.getElementById('sys-status');
    el.innerHTML = env.overall === 'READY'
      ? '<span class="ok">System Ready</span>'
      : `<span class="${env.overall === 'BLOCK' ? 'err' : 'warn'}">System ${esc(env.overall)} — 请打开 Environment Center</span>`;
    if (env.installation_status === 'INSTALLATION_REPAIR_REQUIRED') {
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
if (qs('new') === '1') {
  document.getElementById('new-task-box').style.display = 'block';
  window.setTimeout(() => document.getElementById('task-title').focus(), 0);
}
