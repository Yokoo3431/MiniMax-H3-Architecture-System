// Output Review
const jobId = qs('job');
const requestedProjectId = qs('project');
const errEl = document.getElementById('err');

function showErr(msg) { errEl.className = 'error-banner'; errEl.style.display = 'block'; errEl.textContent = friendlyError(msg, '输出加载失败，请返回 Jobs 重试。'); }
function showContextState(msg) {
  errEl.className = 'notice-banner';
  errEl.style.display = 'block';
  errEl.textContent = msg;
}
function outputFolderPath(outputPath) {
  const separator = String.fromCharCode(92);
  let raw = String(outputPath || '').trim();
  while (raw.endsWith('/') || raw.endsWith(separator)) raw = raw.slice(0, -1);
  const slash = Math.max(raw.lastIndexOf('/'), raw.lastIndexOf(separator));
  return slash > 0 ? raw.slice(0, slash) : '';
}

function setContextLinks(projectId, currentJobId, outputPath) {
  const links = document.getElementById('output-context-actions');
  if (!links) return;
  links.innerHTML = `<a class="btn small" href="jobs.html?project=${encodeURIComponent(projectId || '')}${currentJobId ? `&job=${encodeURIComponent(currentJobId)}` : ''}">返回 Jobs</a>${projectId ? `<a class="btn small ghost" href="workspace.html?project=${encodeURIComponent(projectId)}">返回 Study</a>` : ''}`;
  const folder = outputFolderPath(outputPath);
  if (folder) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn small ghost';
    button.textContent = '打开所在文件夹';
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await post('/api/system/open-path', {path: folder});
      } catch (e) {
        showErr(e.message || '输出文件夹暂时无法打开。');
      } finally {
        button.disabled = false;
      }
    });
    links.appendChild(button);
  }
  links.style.display = 'flex';
}

async function load() {
  if (!jobId) {
    document.getElementById('job-id').textContent = '—';
    showContextState('请选择一个已有输出，或从 Jobs 中打开具体任务。');
    return;
  }
  document.getElementById('job-id').textContent = jobId;
  try {
    const detail = await get(`/api/jobs/${encodeURIComponent(jobId)}/detail`);
    const projectId = detail.project?.id || requestedProjectId || '';
    setContextLinks(projectId, jobId, detail.final_output_path || detail.output_path);
    if (requestedProjectId && detail.project?.id && requestedProjectId !== detail.project.id) {
      showErr('该 Job 不属于当前 Study，请返回 Jobs 重新选择。');
      return;
    }
    if (detail.state !== 'COMPLETED') {
      showContextState(`该任务当前状态：${detail.status_label || detail.state || '未完成'}。完成后才能查看输出。`);
      return;
    }
    const result = await get(`/api/jobs/${jobId}/result`);
    const media = result.output || {};
    const generation = detail.generation_parameters || {};
    const workflowInputs = detail.workflow_snapshot?.workflow?.['6']?.inputs || {};
    const width = generation.width || workflowInputs.width;
    const height = generation.height || workflowInputs.height;
    const fps = generation.fps || detail.workflow_snapshot?.workflow?.['14']?.inputs?.fps;
    const duration = Number.isFinite(Number(generation.duration))
      ? `${Number(generation.duration).toString()}s`
      : '—';
    const frameCount = workflowInputs.length || '—';
    const resolution = width && height ? `${width}×${height}` : '—';
    const video = document.getElementById('output-video');
    const empty = document.getElementById('output-video-empty');
    if (video && empty && media.available && media.media_url) {
      video.src = media.media_url;
      video.hidden = false;
      empty.hidden = true;
    } else if (empty) {
      empty.textContent = '该任务已完成，但浏览器媒体暂不可用。';
    }
    document.getElementById('params').innerHTML = `
      <div class="intent-card">
        <div class="kv"><span class="k">Workflow</span><span>${esc(result.workflow)}</span></div>
        <div class="kv"><span class="k">分辨率 / fps</span><span>${esc(resolution)} / ${esc(fps || '—')}</span></div>
        <div class="kv"><span class="k">时长 / 帧</span><span>${esc(duration)} / ${esc(frameCount)}（H3 帧格）</span></div>
        <div class="kv"><span class="k">Runtime</span><span>${esc(result.runtime === 'native' ? 'Native v0.33.1 · 已验证输出' : 'Prototype')}</span></div>
        <div class="kv"><span class="k">Safe Load</span><span>pread（冻结）</span></div>
        <div class="kv"><span class="k">最终视频</span><span class="small">${esc(media.filename || '—')}</span></div>
      </div>`;

    try {
      const report = await get(`/api/jobs/${jobId}/report`);
      document.getElementById('record').innerHTML = `
      <div class="intent-card">
        <div class="kv"><span class="k">项目</span><span>${esc(report.project_name)}</span></div>
        <div class="kv"><span class="k">Prompt 哈希</span><span class="small">${esc(report.prompt_hash)}</span></div>
        <div class="kv"><span class="k">参考哈希</span><span class="small">${esc(JSON.stringify(report.reference_hashes))}</span></div>
        <div class="kv"><span class="k">Skill 版本</span><span>${esc(report.provenance?.official_skill_revision || '—')}</span></div>
        <div class="kv"><span class="k">审批状态</span><span>${esc(report.provenance?.user_reference_approved ?? '—')}</span></div>
      </div>
      <p class="small muted mt">审计记录（最后 3 条）</p>
      <pre class="small" style="white-space:pre-wrap;">${esc((report.audit_log || []).slice(-3).map((a) => `${a.at} ${a.event} ${a.from}→${a.to}`).join('\n'))}</pre>`;
    } catch (_) {
      document.getElementById('record').innerHTML = '<div class="notice-banner">视频可用；可选生成报告暂不可用。</div>';
    }

    const tree = result.structure;
    const files = tree || {};
    const lines = ['Project/', '├── input/', ...(files.input || []).map((f) => `│   └── ${f}`),
      '├── workflow/', ...(files.workflow || []).map((f) => `│   └── ${f}`),
      '├── prompt/', ...(files.prompt || []).map((f) => `│   └── ${f}`),
      '├── output/', ...(files.output || []).map((f) => `│   └── ${f}`),
      '└── report/', ...(files.report || []).map((f) => `    └── ${f}`)];
    document.getElementById('pkg-tree').textContent = lines.join('\n');
  } catch (e) { showErr(e); }
}

load();
