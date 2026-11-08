/* Native CWA links keep their URLs, tooltips and server-side sorting. */
(() => {
  'use strict';
  // CWA lays book grids out with Isotope, whose 0.4 s slide also runs on every
  // relayout after a viewport change. Read at instantiation by main.js on ready.
  if (window.Isotope) window.Isotope.defaults.transitionDuration = 0;
  // TinyMCE renders its editable area in an iframe with the light oxide skin.
  if (window.tinymce) {
    const darken = editor => {
      const style = () => editor.dom.addStyle('body{background:#0f1217;color:#e6e9ef;font:14px/1.5 "Segoe UI",system-ui,sans-serif;margin:8px}a{color:#d4a85a}');
      if (editor.initialized) style(); else editor.on('init', style);
    };
    tinymce.on('AddEditor', event => darken(event.editor));
    tinymce.get().forEach(darken);
  }

  const svg = paths => {
    const node = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [key, value] of Object.entries({width:'16', height:'16', viewBox:'0 0 24 24', fill:'none',
      stroke:'currentColor', 'stroke-width':'1.65', 'stroke-linecap':'round',
      'stroke-linejoin':'round', 'aria-hidden':'true', focusable:'false'})) node.setAttribute(key, value);
    for (const d of paths) {
      const path = document.createElementNS(node.namespaceURI, 'path');
      path.setAttribute('d', d); node.append(path);
    }
    return node;
  };
  const icons = {
    author: ['M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0', 'M4 21v-2a8 8 0 0 1 16 0v2'],
    added: ['M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H4z', 'M13 8h7v11h-3', 'M17 2v6M14 5h6'],
    published: ['M5 5h14v16H5z', 'M8 2v6M16 2v6M5 10h14', 'M9 14h2v3H9z'],
    series: ['M4 5h12M4 12h12M4 19h12', 'M20 4v2M20 11v2M20 18v2'],
    downloads: ['M12 3v12M7 10l5 5 5-5', 'M4 17v4h16v-4']
  };
  const sorts = {new:['added','down'], old:['added','up'], asc:['title','up'],
    desc:['title','down'], auth_az:['author','up'], auth_za:['author','down'],
    pub_new:['published','down'], pub_old:['published','up'],
    series_asc:['series','up'], series_desc:['series','down'],
    hot_asc:['downloads','up'], hot_desc:['downloads','down']};
  document.documentElement.classList.add('aio-modern');
  const german = document.documentElement.lang.startsWith('de');
  const mobile = window.matchMedia('(max-width: 767px)');
  for (const link of document.querySelectorAll('.filterheader a[id], .filterheader div#asc, .filterheader div#desc')) {
    const sort = sorts[link.id];
    if (!sort) continue;
    const isList = link.hasAttribute('data-id');
    if (!isList && !link.getAttribute('href')) continue;
    const [kind, direction] = sort;
    const label = link.getAttribute('title') || link.getAttribute('data-original-title') ||
      (direction === 'up' ? (german ? 'Aufsteigend sortieren' : 'Sort ascending') : (german ? 'Absteigend sortieren' : 'Sort descending'));
    if (label) link.setAttribute('aria-label', label);
    const symbol = kind === 'title' ? document.createElement('span') : svg(icons[kind]);
    if (kind === 'title') { symbol.textContent = 'A–Z'; symbol.setAttribute('aria-hidden', 'true'); }
    const arrow = svg(direction === 'up' ? ['M12 20V4M6 10l6-6 6 6'] : ['M12 4v16M6 14l6 6 6-6']);
    arrow.classList.add('aio-sort-arrow');
    if (!link.classList.contains('aio-sort')) link.replaceChildren(symbol, arrow);
    link.classList.add('aio-sort');
    link.dataset.sortKind = kind; link.dataset.sortDirection = direction;
    if (link.classList.contains('active')) link.setAttribute('aria-current', 'true');
  }
  const listSort = document.querySelector('.filterheader #asc[data-id]');
  if (listSort) {
    const toolbar = listSort.parentElement;
    toolbar.closest('.aio-main').classList.add('aio-list-page');
    const name = toolbar.querySelector('#sort_name');
    if (name) {
      if (!name.classList.contains('aio-sort')) name.replaceChildren(svg(icons.author), svg(['M4 8h16l-4-4M20 16H4l4 4']));
      name.classList.add('aio-sort');
      name.setAttribute('aria-label', german ? 'Namensdarstellung wechseln' : 'Switch name display');
    }
    for (const control of toolbar.querySelectorAll('div.btn')) {
      control.setAttribute('role', 'button');
      control.tabIndex = 0;
      control.title = control.getAttribute('aria-label') || control.textContent.trim();
      const sync = () => {
        control.setAttribute('aria-pressed', String(control.classList.contains('active')));
        control.removeAttribute('aria-current');
      };
      sync();
      new MutationObserver(sync).observe(control, {attributes:true, attributeFilter:['class']});
      control.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); control.click(); }
      });
    }
  }
  const main = document.querySelector('.aio-main');
  const back = document.querySelector('.aio-back');
  if (back) {
    const prefix = new URL(back.href).pathname.replace(/\/?$/, '/');
    const key = 'cwa-modern-history:' + prefix;
    const valid = value => {
      try {const url = new URL(value);return prefix && url.origin === location.origin && url.pathname.startsWith(prefix) && url.href !== location.href ? url.href : null;} catch (_) {return null;}
    };
    // A referrer can be suppressed by the host/browser. Remember the previous
    // library entry in this tab and preserve it on reload and history restore.
    const state = history.state && typeof history.state === 'object' ? history.state : {};
    let previous = valid(state.aioLocation === location.href ? state.aioPrevious : document.referrer);
    if (state.aioLocation !== location.href && !previous) {
      try {previous = valid(sessionStorage.getItem(key));} catch (_) { /* Storage may be blocked. */ }
    }
    try {history.replaceState({...state, aioLocation:location.href, aioPrevious:previous}, '');} catch (_) { /* History may be restricted. */ }
    const remember = () => {try {sessionStorage.setItem(key, location.href);} catch (_) { /* Optional tab history. */ }};
    remember(); window.addEventListener('pageshow', remember);
    back.setAttribute('aria-label', german ? 'Zurück' : 'Back');
    back.addEventListener('click', event => {
      event.preventDefault(); event.stopImmediatePropagation();
      // Referrer links create a B→C→B→C loop; browser history restores the
      // actual previous entry and its scroll position inside the library frame.
      if (previous && history.length > 1) history.back();
    }, true);
    if (!previous || history.length <= 1) {
      back.setAttribute('aria-disabled', 'true'); back.classList.add('aio-no-back');
    }
  }
  if (main) {
    const resolution = main.querySelector('#resolution_strategy');
    if (resolution && !resolution.closest('.aio-duplicate-options')) {
      const panel = resolution.closest('.settings-container');
      const label = panel.querySelector('h4');
      const options = document.createElement('details'); options.className = 'settings-container aio-duplicate-options';
      const summary = document.createElement('summary'); summary.textContent = label.textContent.trim(); options.append(summary);
      label.remove(); options.append(...panel.childNodes); panel.replaceWith(options);
    }
    const heading = main.querySelector(':scope > h1, :scope > .discover > h2');
    const tools = main.querySelector(':scope > .filterheader, :scope > .discover > .shelf-actions, :scope > .discover > .filterheader');
    if (heading && !main.querySelector(':scope > .aio-page-header')) {
      const header = document.createElement('header'); header.className = 'aio-page-header';
      main.prepend(header); header.append(heading);
      if (document.body.classList.contains('magicshelf')) {
        header.setAttribute('aria-label', heading.textContent.trim());
        heading.remove(); header.classList.add('aio-tools-only');
      }
      if (tools) {const rail = document.createElement('div'); rail.className = 'aio-page-tools'; rail.append(tools); header.append(rail);}
    }
  }
  // filter_grid initializes Isotope synchronously, before deferred theme setup.
  // Re-measure after fallback header setup and cover/font dimensions settle.
  const seriesGrid = document.querySelector('.aio-main > #list');
  if (seriesGrid) {
    if (window.jQuery && window.jQuery(seriesGrid).data('isotope')) window.jQuery(seriesGrid).isotope('option', {transitionDuration: 0});
    const layout = () => {if (window.jQuery && window.jQuery(seriesGrid).data('isotope')) window.jQuery(seriesGrid).isotope('layout');};
    window.addEventListener('load', layout, {once:true});
    if (document.fonts) document.fonts.ready.then(layout);
    seriesGrid.querySelectorAll('img').forEach(img => img.addEventListener('load', layout, {once:true}));
  }
  // The browse navigation lives in the sidebar on desktop and joins the
  // navbar drawer below 768px, the breakpoint the rest of the layout uses.
  const browse = document.querySelector('#scnd-nav'), navigation = document.querySelector('nav.navigation');
  const functionsNav = document.querySelector('#main-nav');
  if (browse && navigation && functionsNav) {
    const placeNav = () => {
      if (mobile.matches) {browse.classList.add('nav', 'navbar-nav'); functionsNav.after(browse);}
      else {browse.classList.remove('nav', 'navbar-nav'); navigation.append(browse);}
    };
    placeNav(); mobile.addEventListener('change', placeNav);
  }
  // Native list items and links stay intact; only each section's visibility changes.
  const functions = document.querySelector('#main-nav > .cwa-switch-theme');
  if (functions) {
    const head = document.createElement('li'); head.className = 'nav-head aio-functions-head';
    head.textContent = german ? 'CWA-Funktionen' : 'CWA functions'; functions.before(head);
  }
  document.querySelectorAll('#scnd-nav .nav-head, #main-nav > .aio-functions-head').forEach((head, index) => {
    const children = []; let next = head.nextElementSibling;
    while (next && !next.classList.contains('nav-head')) { children.push(next); next = next.nextElementSibling; }
    const button = head.querySelector(':scope > button') || document.createElement('button');
    if (!button.parentElement) {button.type = 'button'; button.textContent = head.textContent.trim(); head.replaceChildren(button);}
    head.classList.remove('hidden-xs'); head.classList.add('aio-nav-section');
    const key = `cwa-modern-section-${index}`;
    let expanded = true;
    try { expanded = localStorage.getItem(key) !== 'closed'; } catch (_) { /* Storage can be disabled. */ }
    const hiddenClass = head.classList.contains('aio-functions-head') ? 'aio-functions-hidden' : 'aio-nav-hidden';
    const update = () => {button.setAttribute('aria-expanded', String(expanded)); children.forEach(item => item.classList.toggle(hiddenClass, !expanded));};
    button.addEventListener('click', () => {expanded = !expanded; update();try {localStorage.setItem(key, expanded ? 'open' : 'closed');} catch (_) { /* optional preference */ }});
    update();
  });
  const upload = document.querySelector('#btn-upload');
  const folderTrigger = document.querySelector('.aio-folder-trigger');
  if (upload && folderTrigger) {
    const form = upload.closest('form'), desktopSlot = form.parentElement;
    desktopSlot.classList.add('aio-upload-slot');
    const placeUpload = () => (mobile.matches ? document.querySelector('.navbar > .container-fluid') : desktopSlot).append(form);
    placeUpload(); mobile.addEventListener('change', placeUpload);
    const picker = document.createElement('input'); picker.type = 'file'; picker.multiple = true;
    picker.setAttribute('webkitdirectory', ''); picker.hidden = true; picker.setAttribute('aria-label', german ? 'Ordner hinzufügen' : 'Add folder');
    picker.id = 'aio-folder-picker'; document.body.append(picker);
    folderTrigger.addEventListener('click', () => picker.click());
    picker.addEventListener('change', () => {
      const allowed = upload.accept.split(',').map(value => value.trim().toLowerCase());
      const files = new DataTransfer();
      for (const file of picker.files) {
        if (allowed.includes('.*') || allowed.includes('*') || allowed.some(ext => ext.startsWith('.') && file.name.toLowerCase().endsWith(ext))) files.items.add(file);
      }
      if (!files.files.length) {window.alert(german ? 'Keine unterstützten Buchdateien im Ordner gefunden.' : 'No supported book files found in this folder.'); return;}
      // Use the existing authenticated multipart upload/progress/error handling.
      // Relative directory paths are never sent to the server as destinations.
      upload.files = files.files;
      upload.dispatchEvent(new Event('change', {bubbles:true}));
      picker.value = '';
      document.querySelector('.aio-upload-menu').open = false;
    });
  }
  const search = document.querySelector('form[role="search"]');
  if (search) {
    if (!search.querySelector('.aio-search-icon')) {
      const icon = svg(['M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0', 'm15 15 6 6']);
      icon.classList.add('aio-search-icon'); search.querySelector('.input-group').prepend(icon);
    }
    const submit = search.querySelector('#query_submit');
    submit.setAttribute('aria-label', submit.textContent.trim());
    submit.title = submit.textContent.trim();
    submit.replaceChildren(svg(['M4 12h16M14 6l6 6-6 6']));
  }
})();
