/* AVS global presentation theme. It changes CSS tokens only; no page data or
   product state is reloaded when the user switches themes. */
(function () {
  const STORAGE_KEY = 'avs-theme';
  const THEMES = new Set(['dark', 'light']);
  const root = document.documentElement;

  function readTheme() {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (THEMES.has(saved)) return saved;
    } catch (_) {
      // Storage can be unavailable in locked-down desktop webviews.
    }
    return 'dark';
  }

  function writeTheme(theme) {
    try { window.localStorage.setItem(STORAGE_KEY, theme); } catch (_) { /* best effort */ }
  }

  function applyTheme(theme) {
    const next = THEMES.has(theme) ? theme : 'dark';
    root.dataset.theme = next;
    root.style.colorScheme = next;
    root.classList.toggle('sl-theme-dark', next === 'dark');
    document.querySelectorAll('[data-theme-toggle]').forEach((toggle) => {
      const nextLabel = next === 'dark' ? '切换到浅色主题' : '切换到深色主题';
      toggle.setAttribute('aria-label', nextLabel);
      toggle.setAttribute('title', nextLabel);
      toggle.setAttribute('aria-pressed', String(next === 'light'));
      const icon = toggle.querySelector('[data-theme-icon]');
      if (icon) icon.textContent = next === 'dark' ? '☼' : '☾';
    });
  }

  function addToggle(header) {
    if (!header || header.querySelector('[data-theme-toggle]')) return;
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'avs-theme-toggle';
    toggle.dataset.themeToggle = 'true';
    toggle.innerHTML = '<span data-theme-icon aria-hidden="true">☼</span>';
    toggle.addEventListener('click', () => {
      const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
      writeTheme(next);
      applyTheme(next);
    });
    const spacer = header.querySelector('.spacer');
    header.insertBefore(toggle, spacer || null);
  }

  // Apply before first paint so the five pages do not flash the old palette.
  applyTheme(readTheme());

  function init() {
    document.querySelectorAll('.app-header').forEach(addToggle);
    applyTheme(root.dataset.theme);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
