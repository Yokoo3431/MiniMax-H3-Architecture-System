/* Backend-owned generation-engine indicator shared by every Studio page. */
(function () {
  const bar = document.querySelector('.topbar');
  if (!bar) return;
  const holder = document.createElement('span');
  holder.className = 'engine-status small';
  holder.innerHTML = '<span class="engine-dot"></span><span class="engine-label">生成引擎：检查中</span><button class="btn small engine-restart" style="display:none">重新启动生成引擎</button>';
  bar.appendChild(holder);
  const label = holder.querySelector('.engine-label');
  const button = holder.querySelector('.engine-restart');
  const names = {READY:'就绪', STARTING:'启动中', RUNNING:'运行中', CRASHED:'意外退出', STOPPED:'已停止'};
  async function refresh() {
    try {
      const result = await get('/api/system/engine-status');
      const state = result.state || 'STOPPED';
      label.textContent = `生成引擎：${names[state] || state}`;
      holder.dataset.state = state;
      button.style.display = (state === 'CRASHED' || state === 'STOPPED') ? 'inline-flex' : 'none';
    } catch (_) { label.textContent = '生成引擎：检查中'; }
  }
  button.addEventListener('click', async () => {
    button.disabled = true; button.textContent = '启动中…';
    try {
      const result = await post('/api/system/restart-comfyui', {});
      label.textContent = result.message || '生成引擎：就绪';
    } catch (error) {
      label.textContent = '生成引擎：重启失败';
      holder.title = error.message || 'ComfyUI 重启失败';
    }
    button.disabled = false; button.textContent = '重新启动生成引擎'; refresh();
  });
  refresh();
  setInterval(refresh, 2500);
})();
