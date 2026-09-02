/* UX2-P1 shell switch. Query ?ux2=0 keeps the legacy shell styling available. */
(function () {
  const params = new URLSearchParams(window.location.search);
  const enabled = params.get('ux2') !== '0';
  document.documentElement.dataset.ux2 = enabled ? 'on' : 'off';
  document.documentElement.dataset.ux2Source = enabled ? 'default' : 'query';

  function bindContextualStudyLink() {
    const project = params.get('project');
    const link = document.querySelector('[data-nav-study]');
    if (link && project) link.href = 'workspace.html?project=' + encodeURIComponent(project);
  }

  function restoreLegacyContext() {
    if (enabled || document.querySelector('.ux2-legacy-crumb')) return;
    const labels = {
      'app-home': 'Home',
      'app-study': 'Studio',
      'app-jobs': 'Job Center',
      'app-output': 'Output Review',
      'app-environment': 'System Setup'
    };
    const bodyClass = Array.from(document.body.classList).find((name) => labels[name]);
    const header = document.querySelector('.app-header');
    const spacer = header && header.querySelector('.spacer');
    if (!header || !spacer || !bodyClass) return;
    const crumb = document.createElement('span');
    crumb.className = 'crumb ux2-legacy-crumb';
    crumb.textContent = labels[bodyClass];
    header.insertBefore(crumb, spacer);
    const nav = header.querySelector('.app-nav');
    if (nav) nav.setAttribute('aria-hidden', 'true');
  }

  function bindShell() {
    bindContextualStudyLink();
    restoreLegacyContext();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindShell, { once: true });
  } else {
    bindShell();
  }
})();