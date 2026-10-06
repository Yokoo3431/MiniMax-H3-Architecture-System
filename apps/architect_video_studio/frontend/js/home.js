// Home V2: Recent Tasks + New Video (project = auxiliary tag only)
const tasksEl = document.getElementById('tasks');
const errEl = document.getElementById('err');

function showErr(msg) { errEl.style.display = 'block'; errEl.textContent = msg; }
function escAttr(text) { return esc(text).replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }

function ownerError(error, fallback = '操作失败，请稍后重试。') {
  const message = String(error?.message || error || '');
  if (message.includes('building_stage') || message.includes('建筑阶段')) {
    return '无法创建 Study：请选择有效的建筑阶段。';
  }
  if (message.includes('project_type') || message.includes('Study 类型')) {
    return '无法创建 Study：请选择有效的 Study 类型。';
  }
  return message || fallback;
}

const WF_LABEL = {
  '01_Exterior_Hero': 'Architecture Presentation',
  '02_Day_Night_Transition': 'Day Night',
  '03_Material_Detail': 'Material Detail',
  '04_Drone_Aerial': 'Drone Reveal',
  '05_Slow_Walkthrough': 'Slow Walkthrough',
};

function stateBadge(state) {
  const labels = {
    READY_TO_GENERATE: '素材与提示词已就绪', GENERATING: '正在生成', COMPLETED: '已完成',
    REFERENCE_PENDING: '等待参考图', PROMPT_REVIEW: '准备 Prompt', FAILED: '生成失败',
  };
  const cls = ['COMPLETED', 'READY_TO_GENERATE'].includes(state) ? 'done'
    : ['FAILED', 'REFERENCE_REJECTED'].includes(state) ? 'err'
    : ['GENERATING', 'PROMPT_REVIEW'].includes(state) ? 'warn' : 'state';
  return `<sl-badge class="badge ${cls}" variant="${cls === 'done' ? 'success' : cls === 'err' ? 'danger' : 'neutral'}" pill>${esc(labels[state] || state)}</sl-badge>`;
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
          const studyName = String(p.name || '未命名 Study');
          return `
          <article class="task-card">
            <a class="task-card-main" href="workspace.html?project=${encodeURIComponent(p.id)}" aria-label="打开 Study：${escAttr(studyName)}">
              <div class="ttl">
                <span>${esc(studyName)}</span>
                ${stateBadge(displayState)}
              </div>
              <div class="tags">
                ${wf ? `<sl-tag size="small" class="tag">${esc(WF_LABEL[wf] || wf)}</sl-tag>` : '<sl-tag size="small" class="tag">未选工作流</sl-tag>'}
              </div>
              <div class="foot">
                <span>${esc(p.updated_at)}</span>
                ${prompt ? `<span class="mono">#${esc(prompt.prompt_hash.slice(0, 8))}</span>` : ''}
              </div>
            </a>
            <div class="task-actions">
              <button type="button" class="btn small ghost" data-action="rename" data-project="${escAttr(p.id)}" aria-label="重命名 Study：${escAttr(studyName)}">重命名</button>
              <button type="button" class="btn small ghost" data-action="duplicate" data-project="${escAttr(p.id)}" aria-label="复制 Study：${escAttr(studyName)}">复制</button>
              <button type="button" class="btn small ghost danger" data-action="delete" data-project="${escAttr(p.id)}" aria-label="删除 Study：${escAttr(studyName)}">删除</button>
            </div>
          </article>`;
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
        } catch (e) { showErr(ownerError(e)); }
      });
    });
  } catch (e) {
    tasksEl.textContent = 'Study 列表加载失败；请刷新页面重试。';
    showErr(ownerError(e, '加载 Study 失败。'));
  }
}

async function checkSystem() {
  try {
    const env = await get('/api/system/environment');
    const el = document.getElementById('sys-status');
    const overall = String(env.overall || '').toUpperCase();
    const status = overall === 'READY'
      ? {cls: 'ok', text: '生成环境已就绪'}
      : overall === 'BLOCK'
        ? {cls: 'err', text: '生成环境未就绪：请在环境中心查看需处理项目。'}
        : {cls: 'warn', text: '生成环境仍需检查：请在环境中心查看提示。'};
    el.innerHTML = `<span class="${status.cls}">${status.text}</span>`;
    // Environment is owner-selected. A background health result must not
    // steal the current surface; the Environment link remains available.
    if (env.installation_status === 'INSTALLATION_REPAIR_REQUIRED') {
      el.innerHTML += ' · <a href="setup.html">打开环境中心</a>';
    }
  } catch (_) {
    const el = document.getElementById('sys-status');
    el.textContent = '环境状态暂时无法读取；可打开环境中心重新检查。';
    el.className = 'small warn';
  }
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
  } catch (e) { showErr(ownerError(e, '创建 Study 失败。')); }
});

const homeMain = document.getElementById('main-content');
const showNewStudyOnLoad = qs('new') === '1';
Promise.all([loadTasks(), checkSystem()]).catch((e) => {
  // Both loaders handle expected failures locally; protect the loading shell
  // if an unexpected programming/runtime error escapes.
  tasksEl.textContent = 'Study 列表暂时无法显示，请检查连接后重试。';
  showErr(ownerError(e, '加载 Study 失败。'));
}).finally(() => {
  homeMain?.classList.remove('is-loading');
  homeMain?.setAttribute('aria-busy', 'false');
  document.getElementById('home-loading')?.remove();
  if (showNewStudyOnLoad) {
    document.getElementById('new-task-box').style.display = 'block';
    window.setTimeout(() => document.getElementById('task-title').focus(), 0);
  }
});
