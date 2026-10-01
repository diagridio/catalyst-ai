// <catalyst-ai-install>: install steps for Diagrid Catalyst AI, one tab per client,
// a copy button on every step. Vanilla custom element, Shadow DOM, no dependencies.
//
// No network calls: the steps are bundled in ./data.js (generated, see
// scripts/build_install_data.py in the repository). Copying only touches the
// clipboard, and reports it with a bubbling, composed `catalyst-ai-install:copy`
// event whose detail is { client, item, source }. The host decides what to do with it.
//
// Attributes: variant (compact|full), client (tab id), theme (auto|light|dark),
// source (free text, echoed in the event, e.g. docs, console, website).
//
// Host styling: --catalyst-ai-fg, --catalyst-ai-bg, --catalyst-ai-muted,
// --catalyst-ai-border, --catalyst-ai-accent, --catalyst-ai-font.

import installData from './data.js';

const TAG = 'catalyst-ai-install';
const COPY_EVENT = `${TAG}:copy`;
const THEMES = ['auto', 'light', 'dark'];
const VARIANTS = ['compact', 'full'];
const FEEDBACK_MS = 1800;

/** The client to show: the wanted id when it exists, else the first one. */
export function resolveClient(clients, wanted) {
  return clients.find((c) => c.id === wanted) ?? clients[0];
}

/** Index of the tab a key moves to, or -1 when the key is not a tab key. */
export function nextTabIndex(key, index, count) {
  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return (index + 1) % count;
    case 'ArrowLeft':
    case 'ArrowUp':
      return (index - 1 + count) % count;
    case 'Home':
      return 0;
    case 'End':
      return count - 1;
    default:
      return -1;
  }
}

const STYLE = `
:host {
  --p-fg: #1b1f24; --p-bg: #ffffff; --p-muted: #5b6573; --p-border: #d5dbe3;
  --p-accent: #5b3fd6; --p-code: #f3f5f8;
  --fg: var(--catalyst-ai-fg, var(--p-fg));
  --bg: var(--catalyst-ai-bg, var(--p-bg));
  --muted: var(--catalyst-ai-muted, var(--p-muted));
  --border: var(--catalyst-ai-border, var(--p-border));
  --accent: var(--catalyst-ai-accent, var(--p-accent));
  --code: var(--p-code);
  display: block; color: var(--fg); background: var(--bg);
  font: 14px/1.5 var(--catalyst-ai-font, system-ui, -apple-system, 'Segoe UI', sans-serif);
  border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
}
@media (prefers-color-scheme: dark) {
  :host(:not([theme="light"]):not([theme="dark"])), :host([theme="auto"]) {
    --p-fg: #e7eaf0; --p-bg: #14171c; --p-muted: #9aa5b4; --p-border: #2c333d;
    --p-accent: #a592ff; --p-code: #1d222a;
  }
}
:host([theme="light"]), :host([theme="dark"]) {
  --fg: var(--p-fg); --bg: var(--p-bg); --muted: var(--p-muted);
  --border: var(--p-border); --accent: var(--p-accent);
}
:host([theme="dark"]) {
  --p-fg: #e7eaf0; --p-bg: #14171c; --p-muted: #9aa5b4; --p-border: #2c333d;
  --p-accent: #a592ff; --p-code: #1d222a;
}
:host([hidden]) { display: none; }
* { box-sizing: border-box; }
.intro { margin: 0; padding: 14px 16px 0; color: var(--muted); }
[role="tablist"] { display: flex; gap: 2px; padding: 10px 12px 0; border-bottom: 1px solid var(--border); overflow-x: auto; }
[role="tab"] {
  appearance: none; background: none; border: 0; border-bottom: 2px solid transparent;
  color: var(--muted); font: inherit; font-weight: 600; padding: 8px 12px; cursor: pointer; white-space: nowrap;
}
[role="tab"][aria-selected="true"] { color: var(--fg); border-bottom-color: var(--accent); }
[role="tab"]:focus-visible, button.copy:focus-visible, pre:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
[role="tabpanel"] { padding: 14px 16px 16px; }
ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 14px; }
.title { font-weight: 600; margin: 0; }
.label { font-size: 0.85em; margin: 0.5em 0 0.25em; opacity: 0.8; }
.desc { margin: 2px 0 6px; color: var(--muted); }
.row { display: flex; align-items: flex-start; gap: 8px; margin-top: 6px; }
pre {
  flex: 1; min-width: 0; margin: 0; padding: 8px 10px; background: var(--code); border: 1px solid var(--border);
  border-radius: 6px; font: 12.5px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  white-space: pre-wrap; overflow-wrap: anywhere; max-height: 14em; overflow: auto; user-select: text;
}
button.copy {
  flex: none; font: inherit; font-size: 12px; font-weight: 600; padding: 6px 10px; border-radius: 6px;
  border: 1px solid var(--border); background: var(--bg); color: var(--fg); cursor: pointer;
}
button.copy:hover { border-color: var(--accent); }
.status { min-height: 1.4em; padding: 0 16px 10px; color: var(--muted); font-size: 12px; }
:host([variant="compact"]) .intro, :host([variant="compact"]) .desc { display: none; }
:host([variant="compact"]) [role="tabpanel"] { padding: 10px 12px 12px; }
:host([variant="compact"]) ol { gap: 8px; }
:host([variant="compact"]) .row { margin-top: 4px; }
`;

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'text') node.textContent = value;
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

const Base = globalThis.HTMLElement ?? class {};

export class CatalystAiInstallElement extends Base {
  static get observedAttributes() {
    return ['variant', 'client', 'theme', 'source'];
  }

  #selected = null;
  #timer = 0;
  #root = null;

  connectedCallback() {
    this.#render();
  }

  disconnectedCallback() {
    clearTimeout(this.#timer);
  }

  attributeChangedCallback(name) {
    if (name === 'client') this.#selected = null;
    if (name === 'theme' || name === 'variant') this.#normalise(name);
    if (this.isConnected && name !== 'source') this.#render();
  }

  #normalise(name) {
    const allowed = name === 'theme' ? THEMES : VARIANTS;
    const value = this.getAttribute(name);
    if (value !== null && !allowed.includes(value)) this.removeAttribute(name);
  }

  get client() {
    return resolveClient(installData.clients, this.#selected ?? this.getAttribute('client')).id;
  }

  set client(id) {
    this.setAttribute('client', id);
  }

  get source() {
    return this.getAttribute('source') ?? '';
  }

  set source(value) {
    this.setAttribute('source', value);
  }

  #render() {
    // attributeChangedCallback can run before connectedCallback during upgrade.
    const root = (this.#root ??= this.shadowRoot ?? this.attachShadow({ mode: 'open' }));
    const active = resolveClient(installData.clients, this.#selected ?? this.getAttribute('client'));
    const tabs = installData.clients.map((c) =>
      el('button', {
        role: 'tab',
        type: 'button',
        id: `tab-${c.id}`,
        'data-client': c.id,
        'aria-selected': String(c.id === active.id),
        'aria-controls': 'panel',
        tabindex: c.id === active.id ? '0' : '-1',
        text: c.label,
      }),
    );
    const tablist = el('div', { role: 'tablist', 'aria-label': 'Choose your client' }, tabs);
    tablist.addEventListener('click', (e) => {
      const tab = e.target.closest?.('[role="tab"]');
      if (tab) this.#select(tab.dataset.client, false);
    });
    tablist.addEventListener('keydown', (e) => {
      const index = tabs.indexOf(e.target);
      const next = index < 0 ? -1 : nextTabIndex(e.key, index, tabs.length);
      if (next >= 0) {
        e.preventDefault();
        this.#select(tabs[next].dataset.client, true);
      }
    });

    const steps = el(
      'ol',
      {},
      active.steps.map((s) =>
        el('li', {}, [
          el('p', { class: 'title', text: s.title }),
          el('p', { class: 'desc', text: s.description }),
          ...s.items.map((it) => this.#row(active, it, s.items.length > 1)),
        ]),
      ),
    );
    const panel = el('div', { role: 'tabpanel', id: 'panel', 'aria-labelledby': `tab-${active.id}` }, [steps]);
    const status = el('div', { class: 'status', role: 'status', 'aria-live': 'polite' });

    root.replaceChildren(
      el('style', { text: STYLE }),
      el('p', { class: 'intro', text: 'Connect your assistant to Diagrid Catalyst. Pick your client.' }),
      tablist,
      panel,
      status,
    );
  }

  #row(client, it, showLabel = false) {
    const code = el('pre', { tabindex: '0', text: it.text });
    const button = el('button', { class: 'copy', type: 'button', 'aria-label': `Copy ${it.label}`, text: 'Copy' });
    button.addEventListener('click', () => this.#copy(client.id, it, code, button));
    const row = el('div', { class: 'row' }, [code, button]);
    return showLabel ? el('div', {}, [el('p', { class: 'label', text: it.label }), row]) : row;
  }

  #select(id, focus) {
    this.#selected = id;
    this.#render();
    if (focus) this.#root.getElementById(`tab-${id}`)?.focus();
  }

  async #copy(clientId, it, code, button) {
    let copied = false;
    try {
      await navigator.clipboard.writeText(it.text);
      copied = true;
    } catch {
      this.#selectText(code);
    }
    this.#say(copied ? `Copied ${it.label}.` : 'Copy is unavailable here. The text is selected: press Ctrl+C or Cmd+C.');
    if (copied) {
      button.textContent = 'Copied';
      this.dispatchEvent(
        new CustomEvent(COPY_EVENT, {
          bubbles: true,
          composed: true,
          detail: { client: clientId, item: it.id, source: this.source },
        }),
      );
    }
  }

  #selectText(node) {
    const selection = this.#root.getSelection?.() ?? globalThis.getSelection?.();
    if (!selection) return;
    const range = document.createRange();
    range.selectNodeContents(node);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  #say(message) {
    const status = this.#root.querySelector('.status');
    if (status) status.textContent = message;
    clearTimeout(this.#timer);
    this.#timer = setTimeout(() => {
      if (status) status.textContent = '';
      for (const b of this.#root.querySelectorAll('button.copy')) b.textContent = 'Copy';
    }, FEEDBACK_MS);
  }
}

if (globalThis.customElements && !globalThis.customElements.get(TAG)) {
  globalThis.customElements.define(TAG, CatalystAiInstallElement);
}

export { installData };
export default CatalystAiInstallElement;
