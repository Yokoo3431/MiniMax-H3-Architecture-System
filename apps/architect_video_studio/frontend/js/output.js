// Output Review
const jobId = qs('job');
const errEl = document.getElementById('err');

function showErr(msg) { errEl.style.display = 'block'; errEl.textContent = msg; }

async function load() {
  if (!jobId) { showErr('缺少 job 参数'); return; }
  document.getElementById('job-id').textContent = jobId;
  try {
    const result = await get(`/api/jobs/${jobId}/result`);
    document.getElementById('params').innerHTML = `
      <div class="intent-card">
        <div class="kv"><span class="k">Workflow</span><span>${esc(result.workflow)}</span></div>
        <div class="kv"><span class="k">分辨率 / fps</span><span>1344×768 / 24</span></div>
        <div class="kv"><span class="k">时长 / 帧</span><span>4s / 107（H3 帧格）</span></div>
        <div class="kv"><span class="k">Runtime</span><span>Native v0.33.1（冻结，原型未调用）</span></div>
        <div class="kv"><span class="k">Safe Load</span><span>pread（冻结）</span></div>
      </div>`;

    const report = await get(`/api/jobs/${jobId}/report`);
    document.getElementById('record').innerHTML = `
      <div class="intent-card">
        <div class="kv"><span class="k">项目</span><span>${esc(report.project_name)}</span></div>
        <div class="kv"><span class="k">Prompt 哈希</span><span class="small">${esc(report.prompt_hash)}</span></div>
        <div class="kv"><span class="k">参考哈希</span><span class="small">${esc(JSON.stringify(report.reference_hashes))}</span></div>
        <div class="kv"><span class="k">Skill 版本</span><span>${esc(report.provenance.official_skill_revision || '—')}</span></div>
        <div class="kv"><span class="k">审批状态</span><span>${esc(report.provenance.user_reference_approved)}</span></div>
      </div>
      <p class="small muted mt">审计记录（最后 3 条）</p>
      <pre class="small" style="white-space:pre-wrap;">${esc((report.audit_log || []).slice(-3).map((a) => `${a.at} ${a.event} ${a.from}→${a.to}`).join('\n'))}</pre>`;

    const tree = result.structure;
    const lines = ['Project/', '├── input/', ...tree.input.map((f) => `│   └── ${f}`),
      '├── workflow/', ...tree.workflow.map((f) => `│   └── ${f}`),
      '├── prompt/', ...tree.prompt.map((f) => `│   └── ${f}`),
      '├── output/', ...tree.output.map((f) => `│   └── ${f}`),
      '└── report/', ...tree.report.map((f) => `    └── ${f}`)];
    document.getElementById('pkg-tree').textContent = lines.join('\n');
  } catch (e) { showErr(e.message); }
}

load();
