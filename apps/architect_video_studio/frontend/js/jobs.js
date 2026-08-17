// Job Center
const projectId = qs('project');
const errEl = document.getElementById('err');

function showErr(msg) { errEl.style.display = 'block'; errEl.textContent = msg; }

const PROJECT_STEPS = [
  'CREATED','REFERENCE_PENDING','REFERENCE_APPROVED','INTENT_ANALYSIS',
  'PROMPT_REVIEW','USER_CONFIRM','GPU_RUNNING','QUALITY_CHECK','COMPLETED',
];
const JOB_STEPS = ['CREATED','PREPARING','LOADING_MODEL','SAMPLING','ENCODING','EXPORTING','COMPLETED'];

function badge(state) {
  const map = {
    COMPLETED: 'done', GPU_FAILED: 'err', QUALITY_FAILED: 'err',
    RUNNING: 'warn',
  };
  return `<span class="badge ${map[state] || 'state'}">${esc(state)}</span>`;
}

async function loadProjects() {
  const projects = await get('/api/projects');
  const sel = document.getElementById('project-select');
  sel.innerHTML = projects.map((p) =>
    `<option value="${esc(p.id)}" ${p.id === projectId ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
  if (projects.length) loadJobs(sel.value);
  sel.addEventListener('change', () => { location.href = `jobs.html?project=${sel.value}`; });
}

async function loadJobs(pid) {
  try {
    const jobs = await get(`/api/projects/${pid}/jobs`);
    const body = document.getElementById('jobs-body');
    body.innerHTML = jobs.length ? jobs.map((j) => `
      <tr>
        <td>${esc(j.id)}</td>
        <td>${esc(j.workflow)}</td>
        <td>${badge(j.state)}</td>
        <td>${esc(j.seed)}</td>
        <td>${esc(j.created_at)}</td>
        <td>${j.state === 'COMPLETED'
            ? `<a href="output.html?job=${esc(j.id)}">打开输出</a>`
            : `<span class="muted small">${esc(j.failure_reason || '运行中/待命')}</span>`}</td>
      </tr>`).join('')
      : '<tr><td colspan="6" class="muted">暂无任务</td></tr>';
    const anyRunning = jobs.some((j) => !['COMPLETED','GPU_FAILED'].includes(j.state));
    if (anyRunning) setTimeout(() => loadJobs(pid), 2000);
  } catch (e) { showErr(e.message); }
}

document.getElementById('refresh-btn').addEventListener('click', () => {
  loadJobs(document.getElementById('project-select').value);
});

loadProjects().catch(showErr);
