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

function runtimeLabel(detail) {
  const trace = detail?.execution_trace || {};
  const identity = trace.runtime_identity || detail?.runtime_identity || {};
  const role = identity.runtime_role || identity.target || detail?.runtime_target;
  const version = identity.comfyui_version || trace.runtime_capability?.version || '';
  const roleLabel = role === 'experimental' ? '隔离实验'
    : role === 'production' ? '生产'
      : '运行时身份未记录';
  return `${roleLabel}${version ? ` · ComfyUI ${version}` : ''}`;
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

function deliveryDescription(item) {
  const size = item.delivery_resolution || {};
  const resolution = size.width && size.height ? `${size.width}×${size.height}` : '—';
  const methods = [item.frame_interpolation_method, item.upscale_method,
    item.restoration_method && item.restoration_method !== 'NONE' ? item.restoration_method : null]
    .filter(Boolean).join(' · ') || '仅转码';
  const padding = Number(item.terminal_padding_frames || 0);
  const alignment = padding > 0 ? ` · 末帧对齐 +${padding} 帧` : '';
  return `${resolution} · ${item.delivery_fps} fps · ${methods}${alignment}`;
}

async function loadDeliveries(currentJobId) {
  const list = document.getElementById('delivery-list');
  const form = document.getElementById('delivery-form');
  const submit = document.getElementById('delivery-submit');
  try {
    const state = await get(`/api/jobs/${encodeURIComponent(currentJobId)}/deliveries`);
    form.hidden = !state.available;
    form.style.display = state.available ? 'flex' : 'none';
    if (!state.available) {
      list.textContent = '当前运行环境未提供受管 FFmpeg 交付能力。';
      return;
    }
    const items = state.items || [];
    if (!items.length) {
      list.innerHTML = '<p class="small muted">尚无后处理交付记录。</p>';
      return;
    }
    list.innerHTML = items.slice().reverse().map((item) => {
      const status = item.status === 'READY' ? '已验证' : item.status === 'FAILED' ? '失败，可重试' : '处理中';
      const mediaUrl = item.status === 'READY' ? sameOriginMediaUrl(item.media_url) : '';
      const action = mediaUrl
        ? `<div class="row" style="gap:8px;"><button class="btn small ghost" type="button" data-delivery-id="${esc(item.delivery_id)}" data-delivery-url="${esc(mediaUrl)}">预览</button><a class="btn small primary" href="${esc(mediaUrl)}" download="${esc(mediaDownloadName('avs', currentJobId, item.delivery_id))}">下载交付视频</a></div>` : '';
      const error = item.error_code ? `<span class="small muted">${esc(item.error_code)}</span>` : '';
      return `<div class="intent-card delivery-record">
        <div class="kv"><span class="k">${esc(item.target_resolution || 'NATIVE')} · ${esc(item.delivery_fps)} fps</span><span>${esc(status)}</span></div>
        <div class="kv"><span class="k">输出</span><span>${esc(deliveryDescription(item))}</span></div>
        <div class="kv"><span class="k">文件 / SHA</span><span class="small">${esc(item.size_bytes || '—')} bytes · ${esc((item.output_sha256 || '').slice(0, 16) || '—')}</span></div>
        <div class="row" style="justify-content:space-between;align-items:center;gap:8px;">${error}${action}</div>
      </div>`;
    }).join('');
    list.querySelectorAll('[data-delivery-url]').forEach((button) => {
      button.addEventListener('click', () => {
        const video = document.getElementById('delivery-video');
        video.src = button.dataset.deliveryUrl;
        video.hidden = false;
        document.getElementById('delivery-video-empty').hidden = true;
        const selected = items.find((item) => item.delivery_id === button.dataset.deliveryId);
        document.getElementById('delivery-preview-meta').textContent = selected
          ? `${deliveryDescription(selected)} · duration ${selected.duration_seconds ?? '—'}s · ${selected.video_codec || '—'} · source SHA ${String(selected.source_sha256 || '').slice(0, 16)}`
          : '';
      });
    });
    if (!form.dataset.bound) {
      form.dataset.bound = '1';
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (submit.disabled) return;
        submit.disabled = true;
        const statusEl = document.getElementById('delivery-status');
        statusEl.textContent = '本地 CPU 正在处理；原生 H3 视频不变。请勿重复提交。';
        try {
          const output = await post(`/api/jobs/${encodeURIComponent(currentJobId)}/deliveries`, {
            target_resolution: document.getElementById('delivery-resolution').value,
            delivery_fps: Number(document.getElementById('delivery-fps').value),
          });
          statusEl.textContent = output.status === 'READY'
            ? `交付副本已验证：${deliveryDescription(output)}。原生结果未更改。`
            : `交付副本状态：${output.status || '未知'}。可刷新记录继续检查。`;
          await loadDeliveries(currentJobId);
          const previewButton = document.querySelector(`[data-delivery-id="${CSS.escape(output.delivery_id)}"]`);
          if (previewButton) previewButton.click();
        } catch (error) {
          statusEl.textContent = `交付未完成：${friendlyError(error, '处理失败；可重试后处理，不会重新生成。')}`;
          await loadDeliveries(currentJobId);
        } finally {
          submit.disabled = false;
        }
      });
    }
  } catch (error) {
    list.textContent = `交付记录暂不可用：${friendlyError(error, '请检查 Studio 服务。')}`;
    form.hidden = true;
    form.style.display = 'none';
  }
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
    const mediaUrl = media.available ? sameOriginMediaUrl(media.media_url) : '';
    const download = document.getElementById('output-download');
    if (video && empty && mediaUrl) {
      video.src = mediaUrl;
      video.hidden = false;
      empty.hidden = true;
      if (download) {
        download.href = mediaUrl;
        download.download = mediaDownloadName('avs', jobId, 'native');
        download.hidden = false;
      }
    } else if (empty) {
      empty.textContent = '该任务已完成，但浏览器媒体暂不可用。';
      if (download) {
        download.removeAttribute('href');
        download.hidden = true;
      }
    }
    await loadDeliveries(jobId);
    document.getElementById('params').innerHTML = `
      <div class="intent-card">
        <div class="kv"><span class="k">Workflow</span><span>${esc(result.workflow)}</span></div>
        <div class="kv"><span class="k">分辨率 / fps</span><span>${esc(resolution)} / ${esc(fps || '—')}</span></div>
        <div class="kv"><span class="k">时长 / 帧</span><span>${esc(duration)} / ${esc(frameCount)}（H3 帧格）</span></div>
        <div class="kv"><span class="k">运行时</span><span>${esc(runtimeLabel(detail))}</span></div>
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
