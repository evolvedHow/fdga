/**
 * FDGA Shared Sidebar
 * Include this script in any page that needs the nav sidebar.
 * It auto-detects the current page and marks the correct item active.
 *
 * Usage:
 *   1. Wrap page body in <div id="shell">
 *   2. Include <script src="/js/sidebar.js"></script> in <head>
 *   3. Include <link rel="stylesheet" href="/css/sidebar.css"> in <head>
 */
(function () {
  'use strict';

  const NAV_ITEMS = [
    {
      href: '/',
      label: 'Map Explorer',
      match: ['/', '/index.html'],
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"></polygon>
        <line x1="9" y1="3" x2="9" y2="18"></line>
        <line x1="15" y1="6" x2="15" y2="21"></line>
      </svg>`,
    },
    {
      href: '/frontend/ui_elections.html',
      label: 'Elections Analytics',
      match: ['/frontend/ui_elections.html'],
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="18" y1="20" x2="18" y2="10"></line>
        <line x1="12" y1="20" x2="12" y2="4"></line>
        <line x1="6" y1="20" x2="6" y2="14"></line>
      </svg>`,
    },
    {
      href: '/frontend/analyst.html',
      label: 'AI District Analyst',
      match: ['/frontend/analyst.html'],
      icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        <line x1="9" y1="10" x2="15" y2="10"></line>
        <line x1="9" y1="14" x2="13" y2="14"></line>
      </svg>`,
    },
  ];

  const path = window.location.pathname.replace(/\/$/, '') || '/';

  function isActive(item) {
    return item.match.some(m => {
      const norm = m === '/' ? '/' : m;
      return path === norm || path === norm.replace(/\.html$/, '');
    });
  }

  function buildSidebar() {
    const sidebar = document.createElement('nav');
    sidebar.id = 'fdga-sidebar';

    // Logo
    const logo = document.createElement('div');
    logo.id = 'fdga-sidebar-logo';
    logo.innerHTML = `<a href="/" title="Fair Districts GA">FD</a>`;
    sidebar.appendChild(logo);

    // Nav items
    const navItems = document.createElement('div');
    navItems.className = 'fdga-nav-items';
    NAV_ITEMS.forEach(item => {
      const a = document.createElement('a');
      a.href = item.href;
      a.className = 'fdga-nav-item' + (isActive(item) ? ' active' : '');
      a.setAttribute('data-label', item.label);
      a.setAttribute('title', item.label);
      a.innerHTML = item.icon;
      navItems.appendChild(a);
    });
    sidebar.appendChild(navItems);

    // Footer (about/info)
    const footer = document.createElement('div');
    footer.className = 'fdga-sidebar-footer';
    footer.innerHTML = `
      <a href="https://www.fairdistrictsga.org/" target="_blank"
         class="fdga-nav-item" data-label="FairDistrictsGA.org"
         title="FairDistrictsGA.org" rel="noopener">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
      </a>`;
    sidebar.appendChild(footer);

    return sidebar;
  }

  // Inject sidebar as first child of #shell when DOM is ready
  function inject() {
    const shell = document.getElementById('shell');
    if (!shell) return; // page doesn't use the shell wrapper — skip
    shell.insertBefore(buildSidebar(), shell.firstChild);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject);
  } else {
    inject();
  }
})();
