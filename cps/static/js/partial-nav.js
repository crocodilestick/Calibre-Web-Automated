/* Calibre-Web Automated – SPA navigation client.
 *
 * Architecture (see spa-refactor/Plan.md):
 *   - The server returns a layout-only shell for any non-excluded URL.
 *   - This script reads window.__cwaInitialPath, fetches the matching
 *     body fragment with X-CWA-Fragment: 1, injects it into #main-content,
 *     and from then on intercepts link clicks + popstate to navigate
 *     entirely client-side. Excluded routes (auth, file downloads, readers,
 *     /ajax, OPDS, Kobo, etc.) fall through to a real browser nav.
 */
(function () {
    'use strict';

    var SKIP_PREFIXES = [
        '/login', '/logout', '/register',
        '/remote/', '/verify/',
        '/opds', '/kobo/', '/kobo_auth',
        '/ajax/', '/gdrive',
        '/api/v3', '/api/UserStorage',
        // File downloads under /admin — no 'download' attribute, must bypass SPA fetch.
        '/admin/logdownload/', '/admin/debug',
        // JSON API + SSE stream — never HTML pages.
        '/cwa-library-refresh',
        // File downloads under /cwa- prefixes.
        '/cwa-logs/download/',
        '/cwa-convert-library/download-current-log/',
        '/cwa-epub-fixer/download-current-log/',
        '/sw.js', '/manifest.json'
    ];

    // /read/<int>/<fmt> is the reader; /read/<sort> is a books_list view.
    // /download/<int>/<fmt> is a file download; /download/<sort> is a list.
    var NUMERIC_EXCLUDED_ROOTS = ['/read', '/download'];

    var overlay = null;
    var overlayTimer = null;
    var navigating = false;
    var currentNavToken = 0;

    if (!window.__cwaLoadedScripts) {
        window.__cwaLoadedScripts = new Set();
        // Seed with scripts already on the page so we don't re-load globals.
        document.querySelectorAll('script[src]').forEach(function (s) {
            window.__cwaLoadedScripts.add(s.src);
        });
    }

    // Re-runnable init hooks. Each script populates window.cwaInit.<name>.
    // Order matters: layout fixes first, then bindings.
    window.cwaInit = window.cwaInit || {};
    window.cwaInit.runAll = function () {
        var order = ['mobile', 'tooltips', 'dropdowns', 'commentsReadmore',
                     'directReading', 'isotope', 'infiniteScroll'];
        order.forEach(function (k) {
            var fn = window.cwaInit[k];
            if (typeof fn === 'function') {
                try { fn(); } catch (e) { console.warn('[cwa-spa] cwaInit.' + k + ' failed', e); }
            }
        });
        // Any extra init hooks added later are run after the ordered ones.
        for (var k in window.cwaInit) {
            if (k === 'runAll' || order.indexOf(k) !== -1) continue;
            var fn = window.cwaInit[k];
            if (typeof fn === 'function') {
                try { fn(); } catch (e) { console.warn('[cwa-spa] cwaInit.' + k + ' failed', e); }
            }
        }
    };

    function updateTitle(fragmentRoot) {
        var meta = fragmentRoot.querySelector('meta[name="x-cwa-title"]');
        if (meta && meta.getAttribute('content')) {
            document.title = meta.getAttribute('content');
        }
    }

    function updateSidebarActive(fragmentRoot, pathname) {
        var meta = fragmentRoot.querySelector('meta[name="x-cwa-page"]');
        var page = meta ? meta.getAttribute('content') : '';
        var path = pathname || window.location.pathname;
        document.querySelectorAll('#scnd-nav li').forEach(function (li) {
            var active = false;
            if (page && li.getAttribute('data-page') === page) {
                active = true;
            } else {
                // Per-shelf / per-magic-shelf entries: no data-page, no fixed
                // id — match by their anchor's pathname.
                var a = li.querySelector('a[href]');
                if (a && a.pathname === path) active = true;
            }
            li.classList.toggle('active', active);
        });
    }

    // Track dynamic body classes injected by previous fragments so we can
    // remove them on the next swap. Seed from the <meta name="x-cwa-body-class">
    // emitted by layout.html (and fragment.html) so the seed matches the
    // body's actual page-driven classes — works whether the initial page is
    // the SPA shell (body.spa_shell) or a full-render page like /admin/view
    // (body.admin). Without this, navigating away from an excluded full-
    // render page leaves the old page class on <body>.
    var lastBodyDynClasses = (function () {
        var m = document.head && document.head.querySelector('meta[name="x-cwa-body-class"]');
        if (!m) return [];
        return (m.getAttribute('content') || '').split(/\s+/).filter(Boolean);
    }());

    function updateBodyClass(fragmentRoot) {
        var meta = fragmentRoot.querySelector('meta[name="x-cwa-body-class"]');
        if (!meta) return;
        var dyn = (meta.getAttribute('content') || '')
            .split(/\s+/).filter(Boolean);
        lastBodyDynClasses.forEach(function (c) {
            document.body.classList.remove(c);
        });
        dyn.forEach(function (c) { document.body.classList.add(c); });
        lastBodyDynClasses = dyn;
    }

    /* ------------------------------------------------------------------ */
    /* Overlay (100ms debounce)                                            */
    /* ------------------------------------------------------------------ */

    function scheduleOverlay() {
        cancelOverlay();
        overlayTimer = window.setTimeout(function () {
            overlayTimer = null;
            if (!overlay) overlay = document.getElementById('cwa-nav-overlay');
            if (overlay) {
                overlay.classList.add('cwa-loading');
                overlay.setAttribute('aria-hidden', 'false');
            }
        }, 100);
    }

    function cancelOverlay() {
        if (overlayTimer !== null) {
            window.clearTimeout(overlayTimer);
            overlayTimer = null;
        }
        if (!overlay) overlay = document.getElementById('cwa-nav-overlay');
        if (overlay) {
            overlay.classList.remove('cwa-loading');
            overlay.setAttribute('aria-hidden', 'true');
        }
    }

    /* ------------------------------------------------------------------ */
    /* Skip-list                                                            */
    /* ------------------------------------------------------------------ */

    function pathExcluded(path) {
        if (!path) return false;
        for (var i = 0; i < SKIP_PREFIXES.length; i++) {
            if (path.indexOf(SKIP_PREFIXES[i]) === 0) return true;
        }
        for (var j = 0; j < NUMERIC_EXCLUDED_ROOTS.length; j++) {
            var root = NUMERIC_EXCLUDED_ROOTS[j];
            if (path.indexOf(root + '/') === 0) {
                var tail = path.substring(root.length + 1).split('/', 1)[0];
                if (tail && /^\d+$/.test(tail)) return true;
            }
        }
        return false;
    }

    function shouldSkip(link) {
        if (link.target && link.target !== '' && link.target !== '_self') return true;
        if (link.hostname && link.hostname !== window.location.hostname) return true;
        if (link.hasAttribute('download')) return true;
        // Skip Bootstrap interactive-component links (modal, dropdown, collapse,
        // tabs) but not tooltip/popover — those attach without blocking the href.
        var toggle = link.getAttribute('data-toggle');
        if (toggle && toggle !== 'tooltip' && toggle !== 'popover') return true;
        if (!toggle && link.hasAttribute('data-target')) return true;

        var rawHref = link.getAttribute('href') || '';
        if (!rawHref) return true;
        if (rawHref.charAt(0) === '#') return true;
        if (rawHref.indexOf('javascript:') === 0) return true;
        if (rawHref.indexOf('mailto:') === 0 || rawHref.indexOf('tel:') === 0) return true;

        // Hash-only navigation on the same path — let the browser handle it.
        if (link.pathname === window.location.pathname &&
            link.search === window.location.search &&
            link.hash && link.hash !== '#') {
            return true;
        }

        return pathExcluded(link.pathname);
    }

    /* ------------------------------------------------------------------ */
    /* Content swap + script execution                                     */
    /* ------------------------------------------------------------------ */

    function getMainContainer(root) {
        var doc = root || document;
        return doc.getElementById('main-content') ||
               doc.querySelector('.container-fluid .col-sm-10') ||
               doc.querySelector('.col-sm-10');
    }

    // Returns a promise that resolves when all fragment scripts have finished
    // loading (external) or executing (inline). Callers that depend on page
    // scripts being ready (cwaInit.runAll) should await it.
    function injectFragment(html, targetUrl) {
        var parser = new DOMParser();
        var doc = parser.parseFromString(html, 'text/html');

        var curContainer = getMainContainer();
        if (!curContainer) {
            console.error('[cwa-spa] No main content container in current document');
            return;
        }

        // HTML5 parsing rule: <meta>/<style>/<link> at the start of a fragment
        // (before the first body-level element) get reparented into <head>.
        // Our fragment.html emits the page's x-cwa-* metas AND the per-page
        // {% block header %} content (often a <style> block with the page's
        // CSS) at the top — both end up in doc.head, NOT doc.body. Build a
        // prefix of those head nodes so they apply when injected with the rest
        // of the fragment.
        var headPrefix = '';
        if (doc.head) {
            var headNodes = doc.head.querySelectorAll('meta, style, link');
            for (var i = 0; i < headNodes.length; i++) {
                headPrefix += headNodes[i].outerHTML;
            }
        }

        // The fragment template renders <body>{% block body %}{% block js %}</body>;
        // pull the rendered body wholesale (minus scripts, which we re-exec).
        var sourceBody = doc.body;
        var scriptsDone = Promise.resolve();
        if (!sourceBody) {
            curContainer.innerHTML = headPrefix + html;
        } else {
            // Strip scripts before injecting so innerHTML doesn't keep them as
            // inert tags (and so our re-exec list isn't duplicated).
            var scriptNodes = Array.prototype.slice.call(sourceBody.querySelectorAll('script'));
            scriptNodes.forEach(function (s) { s.parentNode.removeChild(s); });
            curContainer.innerHTML = headPrefix + sourceBody.innerHTML;
            updateBodyClass(curContainer);
            // Resolve target pathname from the URL we're navigating to —
            // history.pushState hasn't fired yet, so window.location is stale.
            var targetPath = null;
            if (targetUrl) {
                try { targetPath = new URL(targetUrl, window.location.href).pathname; }
                catch (e) { /* leave null → updateSidebarActive falls back */ }
            }
            updateSidebarActive(curContainer, targetPath);
            updateTitle(curContainer);
            scriptsDone = executeScripts(scriptNodes);
        }

        if (doc.title) document.title = doc.title;
        return scriptsDone;
    }

    function executeScripts(scriptNodes) {
        // Run scripts sequentially: external scripts must finish loading
        // before later inline scripts run (e.g. magic_shelf_edit.html injects
        // query-builder.standalone.min.js immediately followed by an inline
        // $('#builder').queryBuilder(...) — without this, the inline script
        // fires before the library is available and the rules UI never
        // renders).
        var chain = Promise.resolve();
        scriptNodes.forEach(function (oldScript) {
            chain = chain.then(function () {
                return new Promise(function (resolve) {
                    if (oldScript.src) {
                        var src = oldScript.src;
                        if (window.__cwaLoadedScripts.has(src)) {
                            resolve();
                            return;
                        }
                        window.__cwaLoadedScripts.add(src);
                        var s = document.createElement('script');
                        s.src = src;
                        if (oldScript.type) s.type = oldScript.type;
                        s.onload = function () { resolve(); };
                        s.onerror = function () {
                            console.error('[cwa-spa] failed to load', src);
                            resolve();
                        };
                        document.body.appendChild(s);
                    } else {
                        // Inline scripts always re-execute (page-init code).
                        // Copy ALL attributes — id matters for script tags
                        // used as <script type="text/template" id="…">
                        // template carriers (e.g. #template-shelf-add on
                        // the book-detail page); details.js does
                        // $("#template-shelf-add").html() to feed
                        // _.template(), and without the id we'd pass
                        // undefined and underscore throws.
                        var inline = document.createElement('script');
                        for (var ai = 0; ai < oldScript.attributes.length; ai++) {
                            var a = oldScript.attributes[ai];
                            try { inline.setAttribute(a.name, a.value); }
                            catch (e) { /* ignore odd attribute names */ }
                        }
                        inline.textContent = oldScript.textContent;
                        document.body.appendChild(inline);
                        resolve();
                    }
                });
            });
        });
        return chain;
    }

    function showError() {
        var curContainer = getMainContainer();
        if (curContainer) {
            curContainer.innerHTML =
                '<div class="alert alert-danger" role="alert">' +
                'Failed to load page. Please try again.' +
                '</div>';
        }
    }

    /* ------------------------------------------------------------------ */
    /* Core navigation                                                      */
    /* ------------------------------------------------------------------ */

    // On mobile (≤768px) caliBlur's mobileSupport reparents the sidebar into
    // .navbar-collapse, so it only appears when the hamburger has been
    // toggled (the collapse gains .in). Clicking a sidebar link used to be
    // a full page reload that disposed of the open state for free — with
    // SPA swaps we have to close it ourselves, otherwise the overlay sits
    // on top of the new content.
    function closeMobileSidebar() {
        if (typeof window.$ === 'undefined') return;
        var $open = window.$('.navbar-collapse.collapse.in');
        if (!$open.length) return;
        try { $open.collapse('hide'); }
        catch (e) { $open.removeClass('in'); }
    }

    function navigateTo(url, opts) {
        opts = opts || {};

        // Close any open Bootstrap modal so it doesn't overlay the new page.
        if (typeof window.$ !== 'undefined') {
            try { window.$('.modal.in').modal('hide'); } catch (e) { /* noop */ }
        }

        navigating = true;
        var token = ++currentNavToken;

        // Order matters: kick the XHR off, dismiss the mobile sidebar so its
        // collapse animation runs while the fetch is in flight, THEN arm the
        // overlay. The overlay is debounced (100ms) so a fast cached fetch
        // never paints it; the sidebar close still happens regardless.
        var fetchPromise = fetch(url, {
            credentials: 'same-origin',
            redirect: 'follow',
            headers: {
                'X-CWA-Fragment': '1',
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'text/html'
            }
        });

        closeMobileSidebar();
        scheduleOverlay();

        return fetchPromise.then(function (response) {
            // Distinguish two kinds of follow-redirect outcomes:
            //  (a) the redirect crossed an exclusion boundary (e.g. session
            //      expired → /login) — the response body is the excluded
            //      page's full layout, useless as a fragment; hand control
            //      back to the browser.
            //  (b) same-boundary redirect (e.g. /search → /search/stored/) —
            //      the response is a real fragment, just at a different URL.
            //      Inject it and replace the URL bar to the final target.
            if (response.redirected) {
                var redirectedPath = '';
                try { redirectedPath = new URL(response.url).pathname; }
                catch (e) { /* leave empty → treat as excluded for safety */ }
                if (!redirectedPath || pathExcluded(redirectedPath)) {
                    window.location.href = response.url;
                    return { __cwaRedirected: true };
                }
            }
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            return response.text().then(function (text) {
                return { html: text, finalUrl: response.url, redirected: response.redirected };
            });
        }).then(function (result) {
            if (token !== currentNavToken) return;
            if (result && result.__cwaRedirected) return;

            // After a same-boundary redirect, the URL we asked for and the
            // URL we ended up at differ — use the final one for history,
            // pathname-based sidebar lookups, etc.
            var effectiveUrl = (result && result.redirected && result.finalUrl) ? result.finalUrl : url;

            var scriptsDone = injectFragment(result.html, effectiveUrl) || Promise.resolve();

            // Update browser history.
            try {
                var isSamePage = (new URL(effectiveUrl, window.location.href)).href === window.location.href;
                if (opts.skipPush || isSamePage) {
                    // popstate path — URL already matches, or navigating to current page.
                } else if (opts.replace || (result && result.redirected)) {
                    // Replace (not push) on redirects so the redirect source
                    // doesn't pollute history with an unreachable entry.
                    history.replaceState({ url: effectiveUrl, cwa: true }, '', effectiveUrl);
                } else {
                    history.pushState({ url: effectiveUrl, cwa: true }, '', effectiveUrl);
                }
            } catch (e) {
                console.error('[cwa-spa] history update failed', e);
            }

            // Wait for fragment scripts (e.g. query-builder) to finish loading
            // before re-running shared init hooks — some hooks rely on
            // libraries the fragment just brought in.
            return scriptsDone.then(function () {
                if (window.cwaInit && typeof window.cwaInit.runAll === 'function') {
                    try { window.cwaInit.runAll(); } catch (e) {
                        console.error('[cwa-spa] cwaInit.runAll threw', e);
                    }
                }
                // Scroll after init so no hook can override it. Scroll both
                // window (standard layout) and .col-sm-10 (caliBlur uses it
                // as the overflow-y:auto scroll container instead of window).
                window.scrollTo(0, 0);
                var mainCol = document.querySelector('.col-sm-10');
                if (mainCol) mainCol.scrollTop = 0;
            });
        }).catch(function (err) {
            if (token !== currentNavToken) return;
            console.error('[cwa-spa] navigation failed for', url, err);
            showError();
        }).then(function () {
            if (token === currentNavToken) {
                navigating = false;
                cancelOverlay();
            }
        });
    }

    /* ------------------------------------------------------------------ */
    /* Event wiring                                                         */
    /* ------------------------------------------------------------------ */

    document.addEventListener('click', function (e) {
        if (e.defaultPrevented) return;
        if (e.button !== 0) return;
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

        var link = e.target.closest ? e.target.closest('a') : null;
        if (!link) return;
        if (shouldSkip(link)) return;
        if (!link.href) return;

        e.preventDefault();
        navigateTo(link.href);
    }, false);

    window.addEventListener('popstate', function () {
        navigateTo(window.location.href, { skipPush: true });
    });

    /* ------------------------------------------------------------------ */
    /* Bootstrap                                                            */
    /* ------------------------------------------------------------------ */

    function bootstrap() {
        // Only the SPA shell (cwa_spa_shell.html) sets __cwaInitialPath. If
        // it's absent, the server rendered a full layout-extending page
        // directly (e.g. excluded paths like /admin/* or /login). The page is
        // already in its final state — re-fetching it as a fragment would
        // hit a template that still extends layout.html, then inject the
        // whole chrome into #main-content (sidebar-inside-content, and any
        // click handlers bound on DOMContentLoaded get detached when their
        // targets are replaced — that's why e.g. the Restart modal OK
        // button stops firing). Subsequent SPA clicks still work via the
        // delegated handler; we just skip the initial swap.
        if (!window.__cwaInitialPath) return;

        var initial = window.__cwaInitialPath;
        // Seed history state so the first popstate has something to read.
        try {
            history.replaceState({ url: window.location.href, cwa: true }, '', window.location.href);
        } catch (e) { /* noop */ }
        navigateTo(initial, { replace: true, isInitial: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootstrap);
    } else {
        bootstrap();
    }

    /* ------------------------------------------------------------------ */
    /* Sidebar resize                                                        */
    /* ------------------------------------------------------------------ */

    var SIDEBAR_WIDTH_KEY = 'cwa-sidebar-width';
    var SIDEBAR_MIN = 100;
    var SIDEBAR_MAX = 500;
    var SIDEBAR_MOBILE_BP = 768;

    function sidebarIsMobile() {
        return window.innerWidth < SIDEBAR_MOBILE_BP;
    }

    // caliBlur uses position:absolute for sidebar + main-content; detect it via
    // the body class that layout.html sets when theme == 1.
    function isCaliBlur() {
        return document.body.classList.contains('blur');
    }

    // Width of the left margin inside .col-sm-10 > .container (20% of col-sm-10).
    // Used by the fixed ::before glyphicons on list pages so their width tracks
    // both sidebar resizes and browser window resizes.
    function setListGlyphWidth(sidebarW) {
        var glyphW = Math.round((window.innerWidth - sidebarW) * 0.2);
        document.documentElement.style.setProperty('--list-glyph-width', glyphW + 'px');
    }

    function setSidebarWidth(sidebar, w) {
        if (isCaliBlur()) {
            // One variable drives sidebar, navbar-brand, ::after gap bar,
            // main-content width, and handle position via CSS.
            document.documentElement.style.setProperty('--sidebar-width', w + 'px');
            setListGlyphWidth(w);
        } else {
            sidebar.style.width = w + 'px';
        }
    }

    function applySidebarLayout(sidebar) {
        var row = sidebar.parentElement;
        if (sidebarIsMobile()) {
            row.classList.remove('sidebar-resizable');
            sidebar.style.width = '';
            document.documentElement.style.removeProperty('--sidebar-width');
            document.documentElement.style.removeProperty('--list-glyph-width');
            return;
        }

        var saved = localStorage.getItem(SIDEBAR_WIDTH_KEY);
        var w = saved ? parseInt(saved, 10) : 0;
        if (w < SIDEBAR_MIN || w > SIDEBAR_MAX) w = 0;

        if (isCaliBlur()) {
            if (w) {
                document.documentElement.style.setProperty('--sidebar-width', w + 'px');
                setListGlyphWidth(w);
            }
        } else {
            row.classList.add('sidebar-resizable');
            if (w) sidebar.style.width = w + 'px';
        }
    }

    function initSidebarResize() {
        var handle = document.getElementById('sidebar-resize-handle');
        var sidebar = document.getElementById('sidebar-col');
        if (!handle || !sidebar) return;

        applySidebarLayout(sidebar);

        var resizeTimer;
        window.addEventListener('resize', function () {
            // We dispatch synthetic resize events while dragging (to drive
            // Isotope's relayout); ignore those here so we don't overwrite the
            // in-progress width with the last-saved value.
            if (handle.classList.contains('is-dragging')) return;
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () {
                applySidebarLayout(sidebar);
            }, 100);
        });

        handle.addEventListener('mousedown', function (e) {
            if (e.button !== 0 || sidebarIsMobile()) return;
            e.preventDefault();
            var startX = e.clientX;
            var startWidth = sidebar.getBoundingClientRect().width;

            handle.classList.add('is-dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';

            function onMove(e) {
                var w = Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, startWidth + (e.clientX - startX)));
                setSidebarWidth(sidebar, w);
                // Drive Isotope (and other resize-aware components) the same way
                // a browser window resize does — its built-in resize handler
                // reliably re-measures the container and re-lays out the grid.
                window.dispatchEvent(new Event('resize'));
            }

            function onUp(e) {
                var w = Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, startWidth + (e.clientX - startX)));
                setSidebarWidth(sidebar, w);
                localStorage.setItem(SIDEBAR_WIDTH_KEY, String(Math.round(w)));
                handle.classList.remove('is-dragging');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                window.dispatchEvent(new Event('resize'));
            }

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }

    // partial-nav.js is loaded at the end of <body>, so #sidebar-col already
    // exists here. Apply the persisted width synchronously — before main.js's
    // $(document).ready lays out the Isotope grid — so that first layout measures
    // the resized container width rather than the default. Waiting for
    // DOMContentLoaded would lose that race (main.js's ready fires first).
    if (document.getElementById('sidebar-col')) {
        initSidebarResize();
    } else if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSidebarResize);
    } else {
        initSidebarResize();
    }

    /* ------------------------------------------------------------------ */
    /* Sidebar section collapse (Shelves / Magic Shelves)                  */
    /* ------------------------------------------------------------------ */

    var SHELF_COLLAPSE_KEY = 'cwa-shelf-collapse';

    function getShelfCollapseState() {
        try { return JSON.parse(localStorage.getItem(SHELF_COLLAPSE_KEY) || '{}'); }
        catch (e) { return {}; }
    }

    function applyCollapseSection(section, collapsed) {
        document.querySelectorAll('[data-collapse-section="' + section + '"]').forEach(function (el) {
            el.style.display = collapsed ? 'none' : '';
        });
        var btn = document.querySelector('.js-shelf-section-toggle[data-target="' + section + '"]');
        if (btn) {
            btn.textContent = collapsed ? '▶' : '▼';
            btn.setAttribute('aria-expanded', String(!collapsed));
        }
    }

    function initShelfCollapse() {
        var state = getShelfCollapseState();
        document.querySelectorAll('.js-shelf-section-toggle').forEach(function (btn) {
            var section = btn.getAttribute('data-target');
            applyCollapseSection(section, !!state[section]);
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                var s = getShelfCollapseState();
                s[section] = !s[section];
                localStorage.setItem(SHELF_COLLAPSE_KEY, JSON.stringify(s));
                applyCollapseSection(section, s[section]);
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initShelfCollapse);
    } else {
        initShelfCollapse();
    }
}());
