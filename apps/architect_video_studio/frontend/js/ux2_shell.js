/* UX2-P1 shell switch. Query `?ux2=0` keeps the legacy shell styling available. */
(function () {
  const params = new URLSearchParams(window.location.search);
  const enabled = params.get('ux2') !== '0';
  document.documentElement.dataset.ux2 = enabled ? 'on' : 'off';
  document.documentElement.dataset.ux2Source = enabled ? 'default' : 'query';

  function bindContextualStudyLink() {
    const project = params.get('project');
    const link = document.querySelector('[data-nav-study]');
    if (link && project) link.href = `workspace.html?project=${encodeURIComponent(project)}`;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindContextualStudyLink, { once: true });
  } else {
    bindContextualStudyLink();
  }
})();
