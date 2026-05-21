/* Calibre-Web Automated – SPA navigation client.
 *
 * Architecture (see spa-refactor/Plan.md):
 *   - The server returns a layout-only shell for any non-excluded URL.
 *   - This script reads window.__cwaInitialPath, fetches the matching
 *     body fragment with X-CWA-Fragment: 1, injects it into #main-content,
 *     and from then on intercepts link clicks + popstate to navigate
 *     entirely client-side. Excluded routes (auth, downloads, readers,
 *     admin, /ajax, OPDS, Kobo, etc.) fall through to a real browser nav.
 */
(function () {
    'use strict';

    var SKIP_PREFIXES = [
        '/admin', '/login', '/logout', '/register',
        '/remote/', '/verify/',
        '/opds', '/kobo/', '/kobo_auth',
        '/ajax/', '/cwa-', '/gdrive',
        '/api/v3', '/api/UserStorage',
        '/me', '/sw.js', '/manifest.json'
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

    function updateSidebarActive(fragmentRoot) {
        var meta = fragmentRoot.querySelector('meta[name="x-cwa-page"]');
        if (!meta) return;
        var page = meta.getAttribute('content');
        if (!page) return;
        var targetId = 'nav_' + page;
        document.querySelectorAll('#scnd-nav li').forEach(function (li) {
            li.classList.toggle('active', li.id === targetId);
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
        if (link.hasAttribute('data-toggle') || link.hasAttribute('data-target')) return true;

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

    function injectFragment(html) {
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
        if (!sourceBody) {
            curContainer.innerHTML = headPrefix + html;
        } else {
            // Strip scripts before injecting so innerHTML doesn't keep them as
            // inert tags (and so our re-exec list isn't duplicated).
            var scriptNodes = Array.prototype.slice.call(sourceBody.querySelectorAll('script'));
            scriptNodes.forEach(function (s) { s.parentNode.removeChild(s); });
            curContainer.innerHTML = headPrefix + sourceBody.innerHTML;
            updateBodyClass(curContainer);
            updateSidebarActive(curContainer);
            executeScripts(scriptNodes);
        }

        if (doc.title) document.title = doc.title;
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

    function navigateTo(url, opts) {
        opts = opts || {};

        // Close any open Bootstrap modal so it doesn't overlay the new page.
        if (typeof window.$ !== 'undefined') {
            try { window.$('.modal.in').modal('hide'); } catch (e) { /* noop */ }
        }

        navigating = true;
        var token = ++currentNavToken;
        scheduleOverlay();

        return fetch(url, {
            credentials: 'same-origin',
            redirect: 'follow',
            headers: {
                'X-CWA-Fragment': '1',
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'text/html'
            }
        }).then(function (response) {
            // A redirect that crossed an exclusion boundary (e.g. session
            // expired → /login) — hand control back to the browser.
            if (response.redirected) {
                window.location.href = response.url;
                // Resolve as a sentinel so we don't try to inject anything.
                return { __cwaRedirected: true };
            }
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            return response.text().then(function (text) {
                return { html: text, finalUrl: response.url };
            });
        }).then(function (result) {
            if (token !== currentNavToken) return;
            if (result && result.__cwaRedirected) return;

            injectFragment(result.html);

            // Update browser history.
            try {
                if (opts.skipPush) {
                    // popstate path — URL already matches.
                } else if (opts.replace) {
                    history.replaceState({ url: url, cwa: true }, '', url);
                } else {
                    history.pushState({ url: url, cwa: true }, '', url);
                }
            } catch (e) {
                console.error('[cwa-spa] history update failed', e);
            }

            window.scrollTo(0, 0);

            if (window.cwaInit && typeof window.cwaInit.runAll === 'function') {
                try { window.cwaInit.runAll(); } catch (e) {
                    console.error('[cwa-spa] cwaInit.runAll threw', e);
                }
            }
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
        var initial = window.__cwaInitialPath || window.location.pathname + window.location.search;
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
}());
