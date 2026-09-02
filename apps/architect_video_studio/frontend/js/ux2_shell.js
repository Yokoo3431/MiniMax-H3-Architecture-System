/* UX2-P1 shell switch and route ownership. Query ?ux2=0 keeps the legacy shell styling available. */
(function () {
  const params = new URLSearchParams(window.location.search);
  const enabled = params.get('ux2') !== '0';
  document.documentElement.dataset.ux2 = enabled ? 'on' : 'off';
  document.documentElement.dataset.ux2Source = enabled ? 'default' : 'query';

  const ROUTES = {
    'index.html': 'home',
    'workspace.html': 'study',
    'jobs.html': 'jobs',
    'output.html': 'outputs',
    'setup.html': 'environment',
  };

  function currentRoute() {
    const fileName = (window.location.pathname.split('/').pop() || 'index.html').toLowerCase();
    return ROUTES[fileName] || 'home';
  }

  function withProject(href) {
    const project = params.get('project');
    if (!project || !href || href.startsWith('index.html?new=1')) return href;
    const separator = href.includes('?') ? '&' : '?';
    return href + separator + 'project=' + encodeURIComponent(project);
  }

  function resolveNavigation() {
    const route = currentRoute();
    const currentProject = params.get('project');
    const links = document.querySelectorAll('.app-nav a');

    // Navigation owns active state. Clear first so a reused DOM or history
    // restore can never leave two routes selected.
    links.forEach((link) => {
      link.classList.remove('active');
      link.removeAttribute('aria-current');
    });
    links.forEach((link) => {
      const linkRoute = link.dataset.route;
      const active = linkRoute === route;
      if (active) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page');
      }

      if (linkRoute === 'study') {
        link.href = currentProject
          ? 'workspace.html?project=' + encodeURIComponent(currentProject)
          : 'index.html?new=1';
      } else if (linkRoute === 'jobs' || linkRoute === 'outputs') {
        link.href = withProject(link.getAttribute('href'));
      }
    });
  }

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
    resolveNavigation();
    bindContextualStudyLink();
    restoreLegacyContext();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindShell, { once: true });
  } else {
    bindShell();
  }
})();
