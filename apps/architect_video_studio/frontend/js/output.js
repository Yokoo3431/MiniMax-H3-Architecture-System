// Output Review
const jobId = qs('job');
const requestedProjectId = qs('project');
const errEl = document.getElementById('err');
const resultsLibrary = document.getElementById('results-library');
const jobOutputView = document.getElementById('job-output-view');
let resultGroups = [];
let assemblyResults = [];
let resultProjectNames = new Map();
let supplementaryIssueCount = 0;

function showErr(msg) {
  errEl.className = 'error-banner';
  errEl.setAttribute('role', 'alert');
  errEl.setAttribute('aria-live', 'assertive');
  errEl.style.display = 'block';
  errEl.textContent = friendlyError(msg, '输出加载失败，请返回 Jobs 重试。');
}
function showContextState(msg) {
  errEl.className = 'notice-banner';
  errEl.setAttribute('role', 'status');
  errEl.setAttribute('aria-live', 'polite');
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
  const methods = [item.frame_interpolation_method, deliveryMethodLabel(item.upscale_method),
    item.restoration_method && item.restoration_method !== 'NONE' ? item.restoration_method : null]
    .filter((value) => value && value !== 'NONE').join(' · ') || '仅转码';
  const padding = Number(item.terminal_padding_frames || 0);
  const alignment = padding > 0 ? ` · 末帧对齐 +${padding} 帧` : '';
  return `${resolution} · ${item.delivery_fps} fps · ${methods}${alignment}`;
}

function deliveryFailureMessage(error) {
  const raw = typeof error === 'string' ? error : (error && error.message ? String(error.message) : '');
  if (raw.includes('DELIVERY_RUNTIME_IDENTITY_INCOMPLETE')) {
    return '缺少可验证的运行环境信息，暂时无法生成交付副本；原生视频仍可正常查看。';
  }
  if (raw.includes('DELIVERY_IDENTITY_MISMATCH') || raw.includes('DELIVERY_SOURCE_IDENTITY_UNPROVEN')) {
    return '无法确认交付视频与原任务对应，已安全停止处理；原生视频不受影响。';
  }
  if (/FFMPEG|ffmpeg/i.test(raw)) {
    return '本机视频处理组件暂不可用，交付副本未生成；原生视频不受影响。';
  }
  return '交付记录暂不可用；原生视频仍可正常查看，请稍后重试。';
}

function deliveryItemFailureMessage(code) {
  if (code === 'DELIVERY_RUNTIME_IDENTITY_INCOMPLETE') return '运行环境信息不足，暂不可处理';
  if (code === 'DELIVERY_IDENTITY_MISMATCH' || code === 'DELIVERY_SOURCE_IDENTITY_UNPROVEN') return '来源校验未通过，已停止处理';
  if (code && /FFMPEG/i.test(code)) return '本机视频处理组件暂不可用';
  return code ? '处理未完成，可稍后重试' : '';
}

function resultResolution(width, height) {
  return width && height ? `${width}×${height}` : '分辨率未知';
}

function resultFps(value) {
  const fps = Number(value);
  return Number.isFinite(fps) && fps > 0 ? `${Number.isInteger(fps) ? fps : fps.toFixed(2)} fps` : '帧率未知';
}

function resultDuration(value) {
  const duration = Number(value);
  return Number.isFinite(duration) && duration > 0 ? `${duration.toFixed(2)} 秒` : '';
}

function resultBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function deliveryMethodLabel(value) {
  const method = String(value || '').trim();
  if (!method) return '';
  if (/lanczos/i.test(method)) return 'Lanczos 画布缩放（非 AI 超分）';
  return method;
}

function resultDate(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
}

function resultVersionMarkup(item) {
  const mediaUrl = sameOriginMediaUrl(item.media_url);
  if (!mediaUrl) return '';
  const meta = [item.resolution, resultFps(item.fps), resultDuration(item.duration),
    item.frame_count ? `${item.frame_count} 帧` : '', item.codec || '',
    resultBytes(item.size_bytes), item.method || ''].filter(Boolean).join(' · ');
  const identity = item.kind === 'native' ? 'native' : item.delivery_id || item.assembly_id || 'result';
  return `<div class="results-version">
    <div class="results-version-copy">
      <strong>${esc(item.label)}</strong>
      <div class="small muted results-version-meta">${esc(meta || '媒体信息待验证')}</div>
      ${item.source_label ? `<div class="small muted">来源：${esc(item.source_label)}</div>` : ''}
      ${item.output_sha256 ? `<div class="small muted">SHA-256：${esc(item.output_sha256.slice(0, 16))}…</div>` : ''}
    </div>
    <div class="row results-actions">
      <button class="btn small ghost" type="button" data-result-preview="${esc(mediaUrl)}" data-result-title="${esc(item.label)}" data-result-meta="${esc(meta)}">预览</button>
      <a class="btn small primary" href="${esc(mediaUrl)}" download="${esc(mediaDownloadName('avs', item.job_id || item.queue_id, identity))}">下载</a>
      ${item.job_id ? `<a class="btn small ghost" href="output.html?project=${encodeURIComponent(item.project_id)}&job=${encodeURIComponent(item.job_id)}">结果详情</a>` : ''}
    </div>
  </div>`;
}

function renderResultsLibrary() {
  const projectId = document.getElementById('results-project')?.value || '';
  const needle = String(document.getElementById('results-search')?.value || '').trim().toLowerCase();
  const list = document.getElementById('results-list');
  const jobList = document.getElementById('job-results-items');
  const assemblyList = document.getElementById('assembly-results-items');
  if (!list || !jobList || !assemblyList) return;
  const visibleGroups = resultGroups.filter((group) => {
    if (projectId && group.project_id !== projectId) return false;
    return !needle || `${group.project_name} ${group.workflow} ${group.job_id}`.toLowerCase().includes(needle);
  });
  const visibleAssemblies = assemblyResults.filter((item) => {
    if (projectId && item.project_id !== projectId) return false;
    return !needle || `${item.project_name} ${item.queue_id} ${item.assembly_id} ${item.sequence_id} 长视频组装`.toLowerCase().includes(needle);
  });
  const jobRows = [];
  for (const group of visibleGroups) {
    const versions = group.versions.map(resultVersionMarkup).filter(Boolean).join('');
    if (!versions && !group.unavailable_reason) continue;
    jobRows.push(`<article class="results-group">
      <div class="results-group-heading">
        <div><h4>${esc(group.project_name)} <span class="muted">· ${esc(group.workflow || 'H3 视频')}</span></h4>
          <div class="small muted">Job ${esc(group.job_id)}${group.created_at ? ` · ${esc(resultDate(group.created_at))}` : ''}</div></div>
        <a class="btn small ghost" href="jobs.html?project=${encodeURIComponent(group.project_id)}&job=${encodeURIComponent(group.job_id)}">查看 Job</a>
      </div>
      ${versions ? `<div class="results-versions">${versions}</div>`
        : `<div class="error-banner" role="status">${esc(group.unavailable_reason)}</div>`}
    </article>`);
  }
  const assemblyRows = [];
  for (const item of visibleAssemblies) {
    const versions = item.media_url ? resultVersionMarkup(item) : `<div class="small muted">组装成果当前不可用（${esc(item.status || '状态未知')}）。</div>`;
    assemblyRows.push(`<article class="results-group results-assembly">
      <div class="results-group-heading">
        <div><h4>${esc(item.project_name)} <span class="muted">· 长视频组装</span></h4>
          <div class="small muted">${esc(item.shot_count)} 个镜头 · Sequence ${esc(item.sequence_id || '未记录')} · Assembly ${esc(item.assembly_id)} · Queue ${esc(item.queue_id)}</div></div>
        <a class="btn small ghost" href="workspace.html?project=${encodeURIComponent(item.project_id)}">查看 Study</a>
      </div>
      <div class="results-versions">${versions}</div>
    </article>`);
  }
  jobList.innerHTML = jobRows.length ? jobRows.join('')
    : '<div class="notice-banner">当前筛选条件下没有单 Job 成果。</div>';
  assemblyList.innerHTML = assemblyRows.length ? assemblyRows.join('')
    : '<div class="notice-banner">当前筛选条件下没有长片组装成果。长片完成后会在此独立显示。</div>';
  const visibleCompleted = visibleGroups.length;
  const accessibleNative = visibleGroups.filter((group) => group.versions.some((item) => item.kind === 'native')).length;
  const visibleUnavailable = visibleGroups.filter((group) => Boolean(group.unavailable_reason)).length;
  const versionCount = visibleGroups.reduce((sum, group) => sum + group.versions.length, 0)
    + visibleAssemblies.filter((item) => Boolean(item.media_url)).length;
  const deliveryCount = visibleGroups.reduce((sum, group) => sum
    + group.versions.filter((item) => item.kind === 'delivery').length, 0);
  const assemblyCount = visibleAssemblies.filter((item) => Boolean(item.media_url)).length;
  document.getElementById('results-status').textContent =
    `${visibleCompleted} 个已完成 Job · ${accessibleNative} 个有可访问原生视频 · ${versionCount} 个可访问版本（原生/交付） · ${assemblyCount} 个长视频组装${deliveryCount ? ` · 含 ${deliveryCount} 个交付副本` : ''}${visibleUnavailable ? ` · ${visibleUnavailable} 个已完成 Job 没有可验证视频` : ''}`;
  list.querySelectorAll('[data-result-preview]').forEach((button) => {
    button.addEventListener('click', () => {
      const preview = document.getElementById('results-preview');
      const video = document.getElementById('results-preview-video');
      const source = sameOriginMediaUrl(button.dataset.resultPreview);
      if (!source) return;
      video.src = source;
      video.load();
      preview.hidden = false;
      document.getElementById('results-preview-title').textContent = button.dataset.resultTitle || '成果预览';
      document.getElementById('results-preview-meta').textContent = button.dataset.resultMeta || '';
      preview.scrollIntoView({block: 'nearest', behavior: 'smooth'});
    });
  });
}

async function loadResultsLibrary() {
  const status = document.getElementById('results-status');
  const jobList = document.getElementById('job-results-items');
  const assemblyList = document.getElementById('assembly-results-items');
  status.textContent = '正在读取各 Project / Study 的已保存成果…';
  jobList.textContent = '';
  assemblyList.textContent = '';
  resultGroups = [];
  assemblyResults = [];
  supplementaryIssueCount = 0;
  try {
    const projects = await get('/api/projects');
    resultProjectNames = new Map((projects || []).map((project) => [project.id, project.name || project.id]));
    const select = document.getElementById('results-project');
    const selectedProject = requestedProjectId && resultProjectNames.has(requestedProjectId)
      ? requestedProjectId : select.value;
    select.innerHTML = '<option value="">全部 Project</option>' + (projects || []).map((project) =>
      `<option value="${esc(project.id)}">${esc(project.name || project.id)}</option>`).join('');
    if (selectedProject && resultProjectNames.has(selectedProject)) select.value = selectedProject;

    for (const project of projects || []) {
      let jobs;
      try {
        jobs = await get(`/api/projects/${encodeURIComponent(project.id)}/jobs`);
      } catch (_) {
        supplementaryIssueCount += 1;
        continue;
      }
      for (const job of jobs || []) {
        if (job.state !== 'COMPLETED') continue;
        try {
          const result = await get(`/api/jobs/${encodeURIComponent(job.id)}/result`);
          const output = result.output || {};
          const nativeUrl = output.available ? sameOriginMediaUrl(output.media_url
            || `/api/jobs/${encodeURIComponent(job.id)}/media`) : '';
          if (!nativeUrl) {
            resultGroups.push({
              project_id: project.id, project_name: project.name || project.id,
              job_id: job.id, workflow: job.workflow, created_at: job.created_at,
              versions: [], unavailable_reason: '任务记录显示已完成，但当前没有可验证的视频文件；请打开 Job 查看状态。',
            });
            continue;
          }
          const probe = result.ffprobe || {};
          const params = job.generation_parameters || {};
          const versions = [{
            kind: 'native', job_id: job.id, project_id: project.id,
            label: 'H3 原生输出', media_url: nativeUrl,
            resolution: resultResolution(probe.width || params.width, probe.height || params.height),
            fps: probe.fps || params.fps, duration: probe.duration_seconds,
            frame_count: probe.frame_count, codec: probe.video_codec,
            size_bytes: output.size_bytes,
          }];
          const traceDeliveries = job.execution_trace?.delivery_outputs || [];
          if (traceDeliveries.length) {
            try {
              const deliveryState = await get(`/api/jobs/${encodeURIComponent(job.id)}/deliveries`);
              for (const delivery of deliveryState.items || []) {
                if (delivery.status !== 'READY') continue;
                const deliveryUrl = sameOriginMediaUrl(delivery.media_url);
                if (!deliveryUrl) continue;
                const size = delivery.delivery_resolution || {};
                const isInterpolated = Number(delivery.delivery_fps)
                  > Number(delivery.native_generation_fps || 0);
                const targetLabel = delivery.target_resolution === 'ULTRA_2K' ? '2K 画布放大（非 AI 超分）'
                  : delivery.target_resolution === 'ULTRA_1080' ? '1080p 交付'
                    : '原生画布交付';
                versions.push({
                  kind: 'delivery', job_id: job.id, project_id: project.id,
                  delivery_id: delivery.delivery_id,
                  label: `${targetLabel}${isInterpolated ? ` · ${delivery.delivery_fps} fps 插帧` : ` · ${delivery.delivery_fps} fps`}`,
                  media_url: deliveryUrl,
                  resolution: resultResolution(size.width, size.height),
                  fps: delivery.delivery_fps, duration: delivery.duration_seconds,
                  frame_count: delivery.frame_count, codec: delivery.video_codec,
                  size_bytes: delivery.size_bytes, output_sha256: delivery.output_sha256,
                  method: [deliveryMethodLabel(delivery.upscale_method), delivery.frame_interpolation_method]
                    .filter((value) => value && value !== 'NONE').join(' · '),
                  source_label: `H3 原生 ${resultResolution(
                    (delivery.native_generation_resolution || {}).width,
                    (delivery.native_generation_resolution || {}).height)} / ${resultFps(delivery.native_generation_fps)}`,
                });
              }
            } catch (_) { supplementaryIssueCount += 1; }
          }
          resultGroups.push({
            project_id: project.id, project_name: project.name || project.id,
            job_id: job.id, workflow: job.workflow, created_at: job.created_at,
            versions,
          });
        } catch (_) {
          resultGroups.push({
            project_id: project.id, project_name: project.name || project.id,
            job_id: job.id, workflow: job.workflow, created_at: job.created_at,
            versions: [], unavailable_reason: '任务记录显示已完成，但成果服务暂时无法验证媒体；请打开 Job 后重试。',
          });
        }
      }
      try {
        const longForm = await get(`/api/projects/${encodeURIComponent(project.id)}/long-form`);
        for (const queue of longForm.queues || []) {
          const assembly = queue.assembly || {};
          if (!assembly.assembly_id) continue;
          const media = assembly.media || {};
          const mediaUrl = assembly.status === 'READY'
            ? sameOriginMediaUrl(assembly.media_url) : '';
          assemblyResults.push({
            kind: 'assembly', project_id: project.id,
            project_name: project.name || project.id,
            queue_id: queue.queue_id, assembly_id: assembly.assembly_id,
            sequence_id: queue.director_sequence_id || queue.sequence_id || '',
            status: assembly.status || queue.status,
            shot_count: (queue.shots || []).length,
            media_url: mediaUrl,
            label: '长视频组装',
            resolution: resultResolution(media.width || (queue.target || {}).width,
              media.height || (queue.target || {}).height),
            fps: media.fps || (queue.target || {}).fps,
            duration: media.duration_seconds, frame_count: media.frame_count,
            codec: media.video_codec, size_bytes: assembly.size_bytes || media.size_bytes,
            output_sha256: assembly.output_sha256,
          });
        }
      } catch (_) { supplementaryIssueCount += 1; }
    }
    resultGroups.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
    assemblyResults.sort((a, b) => String(a.project_name).localeCompare(String(b.project_name)));
    renderResultsLibrary();
    const count = resultGroups.reduce((sum, group) => sum + group.versions.length, 0)
      + assemblyResults.filter((item) => Boolean(item.media_url)).length;
    if (supplementaryIssueCount) {
      status.textContent += `；${supplementaryIssueCount} 个项目/交付/组装附加记录暂不可用。共找到 ${count} 个可访问版本。`;
    }
  } catch (_) {
    status.textContent = '成果列表暂不可用，请稍后刷新；已有视频文件不会被修改。';
    jobList.innerHTML = '<div class="error-banner">无法读取单 Job 成果清单。</div>';
    assemblyList.innerHTML = '<div class="error-banner">无法读取长片组装清单。</div>';
  }
}

async function loadDeliveries(currentJobId) {
  const list = document.getElementById('delivery-list');
  const form = document.getElementById('delivery-form');
  const submit = document.getElementById('delivery-submit');
  const statusEl = document.getElementById('delivery-status');
  try {
    const state = await get(`/api/jobs/${encodeURIComponent(currentJobId)}/deliveries`);
    form.hidden = !state.available;
    form.style.removeProperty('display');
    if (!state.available) {
      const identityMissing = state.error_code === 'DELIVERY_RUNTIME_IDENTITY_INCOMPLETE'
        || state.error_code === 'DELIVERY_EXECUTION_IDENTITY_INCOMPLETE';
      const unavailableMessage = identityMissing
        ? '该历史任务缺少创建交付副本所需的运行身份记录；已有原生视频仍可查看和下载。'
        : '当前运行环境未提供受管 FFmpeg 交付能力。';
      list.textContent = unavailableMessage;
      statusEl.textContent = identityMissing
        ? '无法为此历史任务创建新的交付副本；原生结果不受影响。'
        : '当前运行环境暂不支持创建交付副本。';
      return;
    }
    const items = state.items || [];
    statusEl.textContent = items.length ? '已有交付记录，可在下方查看或重试。' : '尚无交付副本。创建后会单独保存，不会改动原生视频。';
    if (!items.length) {
      list.innerHTML = '<p class="small muted">尚无后处理交付记录。</p>';
      return;
    }
    list.innerHTML = items.slice().reverse().map((item) => {
      const status = item.status === 'READY' ? '已验证' : item.status === 'FAILED' ? '失败，可重试' : '处理中';
      const mediaUrl = item.status === 'READY' ? sameOriginMediaUrl(item.media_url) : '';
      const action = mediaUrl
        ? `<div class="row" style="gap:8px;"><button class="btn small ghost" type="button" data-delivery-id="${esc(item.delivery_id)}" data-delivery-url="${esc(mediaUrl)}">预览</button><a class="btn small primary" href="${esc(mediaUrl)}" download="${esc(mediaDownloadName('avs', currentJobId, item.delivery_id))}">下载交付视频</a></div>` : '';
      const error = item.error_code ? `<span class="small muted">${esc(deliveryItemFailureMessage(item.error_code))}</span>` : '';
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
    list.textContent = deliveryFailureMessage(error);
    form.hidden = true;
    form.style.removeProperty('display');
    statusEl.textContent = '交付记录暂不可用；原生视频不受影响。';
  }
}

async function load() {
  if (!jobId) {
    resultsLibrary.hidden = false;
    jobOutputView.hidden = true;
    document.getElementById('output-heading').textContent = '输出与成果';
    document.getElementById('job-id').textContent = '—';
    document.getElementById('err').style.display = 'none';
    document.getElementById('results-project').addEventListener('change', renderResultsLibrary);
    document.getElementById('results-search').addEventListener('input', renderResultsLibrary);
    document.getElementById('results-refresh').addEventListener('click', loadResultsLibrary);
    await loadResultsLibrary();
    return;
  }
  resultsLibrary.hidden = true;
  jobOutputView.hidden = false;
  document.getElementById('output-heading').textContent = '输出审阅';
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
      document.getElementById('delivery-form').hidden = true;
      document.getElementById('delivery-status').textContent = '任务完成后才能创建交付副本。';
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
        <div class="kv"><span class="k">工作流</span><span>${esc(result.workflow)}</span></div>
        <div class="kv"><span class="k">画面 / 帧率</span><span>${esc(resolution)} / ${esc(fps || '—')}</span></div>
        <div class="kv"><span class="k">目标时长 / 帧数</span><span>${esc(duration)} / ${esc(frameCount)}（H3 帧格）</span></div>
        <div class="kv"><span class="k">视频文件</span><span class="small">${esc(media.filename || '—')}</span></div>
      </div>`;

    try {
      const report = await get(`/api/jobs/${jobId}/report`);
      const approved = report.provenance?.user_reference_approved;
      const approvalLabel = approved === true ? '已审批' : approved === false ? '未审批' : '未记录';
      document.getElementById('record').innerHTML = `
      <div class="intent-card">
        <div class="kv"><span class="k">项目</span><span>${esc(report.project_name)}</span></div>
        <div class="kv"><span class="k">参考图审批</span><span>${approvalLabel}</span></div>
        <div class="kv"><span class="k">生成环境</span><span>${esc(runtimeLabel(detail))}</span></div>
      </div>
      <h4>技术溯源</h4>
      <div class="intent-card">
        <div class="kv"><span class="k">Prompt 哈希</span><span class="small">${esc(report.prompt_hash || '—')}</span></div>
        <div class="kv"><span class="k">参考哈希</span><span class="small">${esc(JSON.stringify(report.reference_hashes || []))}</span></div>
        <div class="kv"><span class="k">Skill 版本</span><span>${esc(report.provenance?.official_skill_revision || '—')}</span></div>
        <div class="kv"><span class="k">参考审批记录</span><span>${esc(approved ?? '—')}</span></div>
      </div>
      <p class="small muted mt">最近的任务状态记录</p>
      <pre class="small" style="white-space:pre-wrap;overflow-wrap:anywhere;">${esc((report.audit_log || []).slice(-3).map((a) => `${a.at} ${a.event} ${a.from}→${a.to}`).join('\n'))}</pre>`;
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
