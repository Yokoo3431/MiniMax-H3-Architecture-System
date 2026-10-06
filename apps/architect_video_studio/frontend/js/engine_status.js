/* Backend-owned generation-engine indicator shared by every Studio page. */
(function () {
  const bar = document.querySelector('.topbar');
  if (!bar) return;
  const holder = document.createElement('span');
  holder.className = 'engine-status small';
  holder.title = '此状态仅表示本地 ComfyUI 服务是否可连接；完整生成条件请查看环境状态。';
  holder.innerHTML = '<span class="engine-dot"></span><span class="engine-label">ComfyUI 服务：检查中</span><sl-button class="btn small engine-restart" style="display:none">重新启动生成服务</sl-button>';
  bar.appendChild(holder);
  const label = holder.querySelector('.engine-label');
  const button = holder.querySelector('.engine-restart');
  const names = {READY:'在线', STARTING:'启动中', RUNNING:'运行中', RESTARTING:'重启中', OFFLINE:'离线', CRASHED:'意外退出', STOPPED:'已停止'};
  let refreshing = false;
  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      const result = await get('/api/system/engine-status');
      const state = result.state || 'STOPPED';
      label.textContent = `ComfyUI 服务：${names[state] || '状态未知'}`;
      holder.dataset.state = state;
      button.style.display = (state === 'CRASHED' || state === 'STOPPED' || state === 'OFFLINE') ? 'inline-flex' : 'none';
    } catch (_) { label.textContent = 'ComfyUI 服务：状态暂不可用'; }
    finally { refreshing = false; }
  }
  button.addEventListener('click', async () => {
    button.disabled = true; button.textContent = '启动中…';
    try {
      const result = await post('/api/system/restart-comfyui', {});
      label.textContent = result.message || 'ComfyUI 服务：已启动';
    } catch (error) {
      label.textContent = 'ComfyUI 服务：启动失败';
      holder.title = error.message || 'ComfyUI 重启失败';
    }
    button.disabled = false; button.textContent = '重新启动生成服务'; refresh();
  });
  refresh();
  setInterval(refresh, 5000);
})();
