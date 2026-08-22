/**
 * Catalyst AI split-button — a drop-in "hand this to an AI assistant" control.
 *
 * Zero dependencies. Injects its own styles once. Works in any docs generator,
 * the Catalyst console, and the marketing site.
 *
 * Two presets, one shape:
 *
 *   ask      Open the current docs page in Claude / ChatGPT, or copy it as
 *            Markdown. Needs no backend — docs.diagrid.io already serves
 *            <page>.md with `text/markdown` on every page.
 *
 *   install  Set Catalyst up in Claude Code / Codex / Copilot. Copies the
 *            one-liner; uses a deep link where the client supports one.
 *
 * Usage
 * -----
 *   <div data-catalyst-ai-button data-preset="ask"></div>
 *   <script src="/catalyst-ai-button.js" defer></script>
 *
 * Or imperatively:
 *   CatalystAIButton.mount(el, { preset: 'install', org: 'acme', project: 'default' });
 *
 * Every entry is copy-first: protocol handlers fail *silently* when the target
 * app is not installed, so a deep link is only ever an upgrade over a command
 * the user can paste. That is the whole reason "Copy" is never hidden in a
 * submenu.
 */
(function (global) {
  'use strict';

  // ---------------------------------------------------------------------------
  // Configuration
  // ---------------------------------------------------------------------------

  var DEFAULTS = {
    preset: 'ask',
    docsOrigin: 'https://docs.diagrid.io',
    marketplace: 'diagridio/catalyst-ai',
    // Claude Code's marketplace deep link. Verify it resolves for signed-out
    // users before relying on it; the command below is the guaranteed path.
    claudeCodeDeepLink: 'claude://claude.ai/customize/plugins/marketplaces/add?url=',
    // Set once verified with `npx skills add --list`; 'github-copilot' is the
    // documented slug, 'copilot' is the plausible alias.
    copilotAgentSlug: 'github-copilot',
    org: null,      // Catalyst console only — bakes the user's org into setup
    project: null,  // Catalyst console only
    align: 'right',
  };

  var ICONS = {
    claude: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.6l2.34 6.02L20.4 11l-6.06 2.38L12 19.4l-2.34-6.02L3.6 11l6.06-2.38L12 2.6z"/></svg>',
    openai: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.4" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="12" cy="12" r="3.1"/></svg>',
    copy: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M15 5.5H6A1.5 1.5 0 004.5 7v9" fill="none" stroke="currentColor" stroke-width="1.7"/></svg>',
    check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.8l4.2 4.2L19 7.2" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    terminal: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4.5" width="18" height="15" rx="2.2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M7 10l2.4 2.2L7 14.4M11.6 15h5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    copilot: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.4c-4.7 0-8.5 3.6-8.5 8v3.3c0 3 3.8 5.9 8.5 5.9s8.5-2.9 8.5-5.9V11.4c0-4.4-3.8-8-8.5-8z" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="9.2" cy="13.4" r="1.35"/><circle cx="14.8" cy="13.4" r="1.35"/></svg>',
    chevron: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10l5 5 5-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    external: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 5h5v5M19 5l-7.5 7.5M17 14v4.2A1.8 1.8 0 0115.2 20H5.8A1.8 1.8 0 014 18.2V8.8A1.8 1.8 0 015.8 7H10" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  };

  // ---------------------------------------------------------------------------
  // Styles — injected once, scoped under .cai-*, theme-aware
  // ---------------------------------------------------------------------------

  var STYLE_ID = 'catalyst-ai-button-styles';
  var CSS = [
    '.cai{--cai-fg:#1a1a1c;--cai-fg-dim:#6b6b73;--cai-bg:#fff;--cai-bg-hover:#f4f4f6;',
    '--cai-border:#e0e0e5;--cai-shadow:0 8px 28px rgba(18,18,22,.13),0 1px 2px rgba(18,18,22,.07);',
    '--cai-accent:#3d5afe;--cai-radius:10px;',
    'position:relative;display:inline-block;font:400 14px/1.45 var(--cai-font,ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif);',
    '-webkit-font-smoothing:antialiased;color:var(--cai-fg);text-align:left}',

    '@media (prefers-color-scheme:dark){.cai:not([data-cai-theme="light"]){',
    '--cai-fg:#f2f2f4;--cai-fg-dim:#9a9aa4;--cai-bg:#1c1c20;--cai-bg-hover:#28282e;',
    '--cai-border:#35353d;--cai-shadow:0 8px 28px rgba(0,0,0,.5),0 1px 2px rgba(0,0,0,.4);',
    '--cai-accent:#8c9eff}}',
    '.cai[data-cai-theme="dark"]{--cai-fg:#f2f2f4;--cai-fg-dim:#9a9aa4;--cai-bg:#1c1c20;',
    '--cai-bg-hover:#28282e;--cai-border:#35353d;',
    '--cai-shadow:0 8px 28px rgba(0,0,0,.5),0 1px 2px rgba(0,0,0,.4);--cai-accent:#8c9eff}',

    /* split button */
    '.cai__split{display:inline-flex;align-items:stretch;border:1px solid var(--cai-border);',
    'border-radius:var(--cai-radius);background:var(--cai-bg);overflow:hidden}',
    '.cai__primary,.cai__toggle{display:inline-flex;align-items:center;gap:8px;background:none;',
    'border:0;color:inherit;font:inherit;cursor:pointer;padding:8px 12px;transition:background .12s ease}',
    '.cai__primary:hover,.cai__toggle:hover{background:var(--cai-bg-hover)}',
    '.cai__primary:focus-visible,.cai__toggle:focus-visible,.cai__item:focus-visible{',
    'outline:2px solid var(--cai-accent);outline-offset:-2px}',
    '.cai__toggle{padding:8px 7px;border-left:1px solid var(--cai-border)}',
    '.cai__toggle svg{width:16px;height:16px;transition:transform .16s ease}',
    '.cai[data-open="true"] .cai__toggle svg{transform:rotate(180deg)}',
    '.cai__primary .cai__ico{width:16px;height:16px;flex:0 0 auto}',
    '.cai__label{white-space:nowrap;font-weight:500}',

    /* menu */
    '.cai__menu{position:absolute;top:calc(100% + 8px);min-width:288px;z-index:70;',
    'background:var(--cai-bg);border:1px solid var(--cai-border);border-radius:12px;',
    'box-shadow:var(--cai-shadow);padding:6px;margin:0;list-style:none;',
    'opacity:0;transform:translateY(-5px) scale(.985);pointer-events:none;',
    'transition:opacity .14s ease,transform .14s ease}',
    '.cai[data-align="right"] .cai__menu{right:0}',
    '.cai[data-align="left"] .cai__menu{left:0}',
    '.cai[data-open="true"] .cai__menu{opacity:1;transform:none;pointer-events:auto}',
    '@media (prefers-reduced-motion:reduce){.cai__menu{transition:none}.cai__toggle svg{transition:none}}',

    '.cai__item{display:flex;align-items:flex-start;gap:11px;width:100%;padding:9px 10px;',
    'background:none;border:0;border-radius:8px;color:inherit;font:inherit;cursor:pointer;',
    'text-align:left;text-decoration:none;transition:background .1s ease}',
    '.cai__item:hover{background:var(--cai-bg-hover)}',
    '.cai__ico{width:17px;height:17px;flex:0 0 auto;margin-top:2px;color:var(--cai-fg)}',
    '.cai__ico svg{width:100%;height:100%;display:block;fill:currentColor}',
    '.cai__primary .cai__ico svg,.cai__toggle svg{fill:currentColor}',
    '.cai__txt{min-width:0;flex:1}',
    '.cai__t{display:flex;align-items:center;gap:5px;font-weight:500}',
    '.cai__t .cai__ext{width:12px;height:12px;opacity:.5;flex:0 0 auto}',
    '.cai__d{color:var(--cai-fg-dim);font-size:12.5px;margin-top:1px}',
    '.cai__code{font:400 12px/1.4 var(--cai-mono,ui-monospace,SFMono-Regular,Menlo,monospace);',
    'color:var(--cai-fg-dim);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.cai__sep{height:1px;background:var(--cai-border);margin:5px 8px}',
    '.cai__sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}',
  ].join('');

  function injectStyles() {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /**
   * Markdown URL for a docs page. docs.diagrid.io serves `<path>.md` with
   * `text/markdown` on every page — verified across getting-started, develop,
   * operate and references. Directory-style roots need an explicit index.
   */
  function markdownUrl(href, docsOrigin) {
    var u;
    try { u = new URL(href); } catch (e) { return null; }
    var p = u.pathname.replace(/\/+$/, '');
    if (!p) p = '/index';
    return u.origin + p + '.md' + (docsOrigin ? '' : '');
  }

  function askPrompt(pageUrl, mdUrl, title) {
    return 'Read ' + mdUrl + ' — the Diagrid Catalyst documentation page' +
      (title ? ' "' + title + '"' : '') + ' (' + pageUrl + ').\n\n' +
      'Use it to answer my questions about Catalyst. If I ask for code, target the ' +
      'language and framework I name and keep it consistent with this page.';
  }

  async function copyText(text) {
    if (global.navigator && navigator.clipboard && global.isSecureContext) {
      try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall through */ }
    }
    // Fallback for http:// origins and older browsers.
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;top:-1000px;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch (e) { return false; }
  }

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  // ---------------------------------------------------------------------------
  // Entry builders
  // ---------------------------------------------------------------------------

  function askEntries(cfg) {
    // `pageUrl` override exists for two real cases: SPA docs where
    // location.href lags the rendered route, and previews served off a
    // different origin than the published docs.
    var pageUrl = cfg.pageUrl ||
      (global.location ? location.href.split('#')[0] : cfg.docsOrigin);
    var mdUrl = cfg.markdownUrl || markdownUrl(pageUrl, cfg.docsOrigin) || pageUrl;
    var title = cfg.pageTitle ||
      (document.title || '').replace(/\s*[|—-]\s*Diagrid.*$/i, '').trim();
    var q = encodeURIComponent(askPrompt(pageUrl, mdUrl, title));

    return [
      {
        id: 'claude',
        icon: ICONS.claude,
        title: 'Open in Claude',
        desc: 'Ask questions about this page',
        href: 'https://claude.ai/new?q=' + q,
        external: true,
        primary: true,
      },
      {
        id: 'chatgpt',
        icon: ICONS.openai,
        title: 'Open in ChatGPT',
        desc: 'Ask questions about this page',
        href: 'https://chatgpt.com/?q=' + q,
        external: true,
      },
      { sep: true },
      {
        id: 'copy-page',
        icon: ICONS.copy,
        title: 'Copy page as Markdown',
        desc: 'Paste into any assistant',
        // Fetch the .md the docs site already serves, so the assistant gets
        // clean prose instead of scraped DOM.
        action: async function () {
          var text;
          try {
            var r = await fetch(mdUrl, { headers: { Accept: 'text/markdown,text/plain' } });
            text = r.ok ? await r.text() : null;
          } catch (e) { text = null; }
          if (!text) text = document.title + '\n' + pageUrl; // never copy nothing
          return copyText(text);
        },
      },
      {
        id: 'copy-link',
        icon: ICONS.copy,
        title: 'Copy Markdown link',
        desc: mdUrl.replace(/^https?:\/\//, ''),
        action: function () { return copyText(mdUrl); },
      },
    ];
  }

  function installEntries(cfg) {
    var mp = cfg.marketplace;
    var slug = cfg.copilotAgentSlug;
    var ctx = '';
    if (cfg.org) {
      // The console knows who you are, so it can hand over real context and
      // skip the first "which project?" round trip. Docs cannot do this.
      ctx = '\n\n# then, in your assistant:\n#   Set up Diagrid Catalyst for org ' +
        cfg.org + (cfg.project ? ' project ' + cfg.project : '');
    }

    var claudeCmd = 'claude plugin marketplace add ' + mp +
      ' && claude plugin install catalyst-ai@diagrid' + ctx;
    var codexCmd = "npx skills add " + mp + " --agent codex --skill '*' --yes" + ctx;
    var copilotCmd = 'npx skills add ' + mp + ' --agent ' + slug + " --skill '*' --yes" + ctx;

    return [
      {
        id: 'claude-code',
        icon: ICONS.claude,
        title: 'Claude Code',
        desc: 'Skills, MCP server and commands',
        code: 'claude plugin install catalyst-ai@diagrid',
        primary: true,
        action: function () { return copyText(claudeCmd); },
        // A deep link is an upgrade, never the contract — it fails silently
        // when Claude is not installed.
        deepLink: cfg.claudeCodeDeepLink
          ? cfg.claudeCodeDeepLink + encodeURIComponent('https://github.com/' + mp)
          : null,
      },
      {
        id: 'codex',
        icon: ICONS.terminal,
        title: 'OpenAI Codex',
        desc: 'Skills via the open Agent Skills spec',
        code: 'npx skills add ' + mp + ' --agent codex',
        action: function () { return copyText(codexCmd); },
      },
      {
        id: 'copilot',
        icon: ICONS.copilot,
        title: 'GitHub Copilot',
        desc: 'CLI, coding agent and VS Code',
        code: 'npx skills add ' + mp + ' --agent ' + slug,
        action: function () { return copyText(copilotCmd); },
      },
      { sep: true },
      {
        id: 'all',
        icon: ICONS.copy,
        title: 'Copy all three',
        desc: 'Install into every client at once',
        action: function () {
          // Repeated -a flags, not comma-separated. Verified against skills
          // 1.5.22: `-a a,b,c` and `-a "a b c"` both fail with "Invalid agents"
          // even though every slug is individually valid, so the comma form the
          // upstream README documents installs nothing.
          return copyText('npx skills add ' + mp +
            ' -a claude-code -a codex -a ' + slug + " -s '*' -y");
        },
      },
      {
        id: 'docs',
        icon: ICONS.external,
        title: 'Setup guide',
        desc: 'Authentication, projects and quotas',
        href: cfg.docsOrigin + '/getting-started/quickstarts/ai-agents/',
        external: true,
      },
    ];
  }

  // ---------------------------------------------------------------------------
  // Component
  // ---------------------------------------------------------------------------

  function mount(host, options) {
    if (!host || host.__caiMounted) return null;
    injectStyles();

    var cfg = Object.assign({}, DEFAULTS, options || {});
    var entries = cfg.preset === 'install' ? installEntries(cfg) : askEntries(cfg);
    var actionable = entries.filter(function (e) { return !e.sep; });
    var lead = actionable.find(function (e) { return e.primary; }) || actionable[0];

    var root = el('div', 'cai');
    root.setAttribute('data-align', cfg.align);
    root.setAttribute('data-preset', cfg.preset);
    if (cfg.theme) root.setAttribute('data-cai-theme', cfg.theme);
    root.__caiMounted = true;

    var menuId = 'cai-menu-' + Math.random().toString(36).slice(2, 9);
    var split = el('div', 'cai__split');

    // Primary: the lead entry, one click, no menu needed.
    var primary = el('button', 'cai__primary');
    primary.type = 'button';
    primary.innerHTML = '<span class="cai__ico">' + lead.icon + '</span>' +
      '<span class="cai__label">' + (cfg.preset === 'install'
        ? 'Set up in ' + lead.title
        : lead.title) + '</span>';

    var toggle = el('button', 'cai__toggle', ICONS.chevron);
    toggle.type = 'button';
    toggle.setAttribute('aria-haspopup', 'true');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-controls', menuId);
    toggle.appendChild(el('span', 'cai__sr', 'More options'));

    split.appendChild(primary);
    split.appendChild(toggle);
    root.appendChild(split);

    var menu = el('ul', 'cai__menu');
    menu.id = menuId;
    menu.setAttribute('role', 'menu');
    root.appendChild(menu);

    var itemNodes = [];

    entries.forEach(function (entry) {
      if (entry.sep) {
        var li = el('li', null);
        li.setAttribute('role', 'presentation');
        li.appendChild(el('div', 'cai__sep'));
        menu.appendChild(li);
        return;
      }
      var li = el('li', null);
      li.setAttribute('role', 'none');
      var node = entry.href && !entry.action
        ? el('a', 'cai__item')
        : el('button', 'cai__item');
      if (node.tagName === 'A') {
        node.href = entry.href;
        node.target = '_blank';
        node.rel = 'noopener noreferrer';
      } else {
        node.type = 'button';
      }
      node.setAttribute('role', 'menuitem');
      node.innerHTML =
        '<span class="cai__ico">' + entry.icon + '</span>' +
        '<span class="cai__txt">' +
          '<span class="cai__t">' + entry.title +
            (entry.external ? '<span class="cai__ext">' + ICONS.external + '</span>' : '') +
          '</span>' +
          '<span class="cai__d">' + entry.desc + '</span>' +
          (entry.code ? '<span class="cai__code">' + entry.code + '</span>' : '') +
        '</span>';
      li.appendChild(node);
      menu.appendChild(li);
      itemNodes.push(node);

      if (entry.action) {
        node.addEventListener('click', function (ev) {
          ev.preventDefault();
          run(entry, node);
        });
      } else {
        node.addEventListener('click', function () { close(); });
      }
    });

    // Confirm in place. A copy with no feedback reads as a dead button.
    function flash(node, label) {
      var t = node.querySelector('.cai__t');
      var ico = node.querySelector('.cai__ico');
      if (!t || node.__caiBusy) return;
      node.__caiBusy = true;
      var t0 = t.innerHTML, i0 = ico.innerHTML;
      t.innerHTML = label;
      ico.innerHTML = ICONS.check;
      setTimeout(function () {
        t.innerHTML = t0; ico.innerHTML = i0; node.__caiBusy = false;
      }, 1600);
    }

    async function run(entry, node) {
      var ok = true;
      try { ok = await entry.action(); } catch (e) { ok = false; }
      flash(node, ok ? 'Copied' : 'Press ' +
        (/Mac|iP(hone|ad)/.test(navigator.platform || '') ? '⌘' : 'Ctrl') + 'C');
      if (ok && entry.deepLink) {
        // Command is already on the clipboard, so if the handler does nothing
        // the user still has a working path.
        try { global.location.href = entry.deepLink; } catch (e) { /* ignore */ }
      }
      cfg.onSelect && cfg.onSelect(entry.id);
      if (ok) setTimeout(close, 900);
    }

    primary.addEventListener('click', function () {
      if (lead.action) {
        run(lead, itemNodes[entries.filter(function (e) { return !e.sep; }).indexOf(lead)] || itemNodes[0]);
      } else if (lead.href) {
        global.open(lead.href, '_blank', 'noopener');
        cfg.onSelect && cfg.onSelect(lead.id);
      }
    });

    function open() {
      root.setAttribute('data-open', 'true');
      toggle.setAttribute('aria-expanded', 'true');
      document.addEventListener('click', onDocClick, true);
      document.addEventListener('keydown', onKey, true);
    }
    function close() {
      root.removeAttribute('data-open');
      toggle.setAttribute('aria-expanded', 'false');
      document.removeEventListener('click', onDocClick, true);
      document.removeEventListener('keydown', onKey, true);
    }
    function onDocClick(ev) { if (!root.contains(ev.target)) close(); }
    function onKey(ev) {
      if (ev.key === 'Escape') { close(); toggle.focus(); return; }
      if (ev.key !== 'ArrowDown' && ev.key !== 'ArrowUp') return;
      ev.preventDefault();
      var i = itemNodes.indexOf(document.activeElement);
      var next = ev.key === 'ArrowDown'
        ? (i + 1) % itemNodes.length
        : (i <= 0 ? itemNodes.length - 1 : i - 1);
      itemNodes[next].focus();
    }

    toggle.addEventListener('click', function () {
      root.hasAttribute('data-open') ? close() : open();
    });

    host.appendChild(root);
    return { root: root, open: open, close: close };
  }

  function auto() {
    var nodes = document.querySelectorAll('[data-catalyst-ai-button]');
    Array.prototype.forEach.call(nodes, function (n) {
      mount(n, {
        preset: n.getAttribute('data-preset') || undefined,
        align: n.getAttribute('data-align') || undefined,
        theme: n.getAttribute('data-theme') || undefined,
        org: n.getAttribute('data-org') || undefined,
        project: n.getAttribute('data-project') || undefined,
        marketplace: n.getAttribute('data-marketplace') || undefined,
        pageUrl: n.getAttribute('data-page-url') || undefined,
        pageTitle: n.getAttribute('data-page-title') || undefined,
      });
    });
  }

  var api = { mount: mount, auto: auto, markdownUrl: markdownUrl, DEFAULTS: DEFAULTS };
  global.CatalystAIButton = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;

  if (typeof document !== 'undefined') {
    document.readyState === 'loading'
      ? document.addEventListener('DOMContentLoaded', auto)
      : auto();
  }
})(typeof window !== 'undefined' ? window : globalThis);
