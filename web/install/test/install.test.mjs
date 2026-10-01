// Run: node --test test/   (from web/install)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const pkg = join(here, '..');
const repo = join(pkg, '..', '..');
const json = JSON.parse(readFileSync(join(pkg, 'install.json'), 'utf8'));
const readme = readFileSync(join(repo, 'README.md'), 'utf8');
const squash = (s) => s.split(/\s+/).filter(Boolean).join(' ');

test('the component file parses', () => {
  const r = spawnSync(process.execPath, ['--check', join(pkg, 'catalyst-ai-install.js')], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
});

test('data.js and install.json carry the same data', async () => {
  const { default: data, installData } = await import('../data.js');
  assert.deepEqual(data, json);
  assert.equal(installData, data);
});

test('data shape: four clients, unique ids, non-empty text, the production MCP URL only', () => {
  assert.equal(json.schema, 1);
  assert.equal(json.mcpUrl, 'https://mcp.cloud.r1.diagrid.io/mcp');
  assert.deepEqual(json.clients.map((c) => c.id), ['claude-code', 'codex', 'copilot-cli', 'vscode']);
  for (const c of json.clients) {
    assert.ok(c.label && c.steps.length > 0, c.id);
    const ids = new Set();
    for (const s of c.steps) {
      assert.ok(s.title && s.description && s.items.length > 0, `${c.id}/${s.id}`);
      for (const i of s.items) {
        assert.ok(i.id && i.label && i.text.trim() && ['bash', 'json', 'text'].includes(i.lang), `${c.id}/${s.id}/${i.id}`);
        const key = `${s.id}/${i.id}`;
        assert.ok(!ids.has(key), `duplicate item ${c.id}/${key}`);
        ids.add(key);
        assert.equal(i.readme, undefined, 'build-time rules must not ship');
      }
    }
  }
  const all = JSON.stringify(json);
  assert.ok(!/diagrid\s+[a-z]/.test(all.replace(/diagrid(io)?\//g, '')), 'no CLI invocation');
  for (const host of all.match(/[a-z0-9.-]+\.diagrid\.(io|dev)/gi) ?? []) {
    assert.ok(['mcp.cloud.r1.diagrid.io', 'catalyst.diagrid.io'].includes(host), host);
  }
});

test('commands/ drift: every command is in the data, name, description and prompt', () => {
  const files = readdirSync(join(repo, 'commands')).filter((f) => f.endsWith('.md')).sort();
  assert.deepEqual(json.commands.map((c) => c.id).sort(), files.map((f) => f.replace(/\.md$/, '')));
  for (const f of files) {
    const raw = readFileSync(join(repo, 'commands', f), 'utf8');
    const m = raw.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
    assert.ok(m, f);
    const id = f.replace(/\.md$/, '');
    const cmd = json.commands.find((c) => c.id === id);
    assert.equal(cmd.name, `/catalyst-ai:${id}`);
    assert.equal(cmd.description, m[1].replace(/^description:\s*/, '').trim());
    assert.equal(cmd.prompt, m[2].trim());
  }
});

test('README drift: client snippets appear in the README', () => {
  const flat = squash(readme);
  const exact = {
    'claude-code': ['marketplace-add', 'plugin-install'],
    codex: ['mcp-add', 'mcp-login'],
    'copilot-cli': ['mcp-config'],
    vscode: ['mcp-config'],
  };
  for (const [clientId, itemIds] of Object.entries(exact)) {
    const client = json.clients.find((c) => c.id === clientId);
    for (const itemId of itemIds) {
      const it = client.steps.flatMap((s) => s.items).find((i) => i.id === itemId);
      assert.ok(it, `${clientId}/${itemId}`);
      assert.ok(flat.includes(squash(it.text)), `${clientId}/${itemId} is not in README.md`);
    }
  }
});

test('the generator agrees (check mode)', (t) => {
  const r = spawnSync('python3', [join(repo, 'scripts', 'build_install_data.py'), '--check'], { encoding: 'utf8' });
  if (r.error) return t.skip('python3 not available');
  assert.equal(r.status, 0, r.stderr);
});

test('smoke: the element registers with its attributes and the helpers behave', async () => {
  const defined = new Map();
  globalThis.HTMLElement = class {};
  globalThis.customElements = { get: (n) => defined.get(n), define: (n, c) => defined.set(n, c) };
  const mod = await import('../catalyst-ai-install.js');
  const Element = defined.get('catalyst-ai-install');
  assert.ok(Element, 'registered');
  assert.equal(Element, mod.default);
  assert.deepEqual(Element.observedAttributes, ['variant', 'client', 'theme', 'source']);

  assert.equal(mod.resolveClient(json.clients, 'vscode').id, 'vscode');
  assert.equal(mod.resolveClient(json.clients, 'nope').id, 'claude-code');
  assert.equal(mod.resolveClient(json.clients, null).id, 'claude-code');
  assert.equal(mod.nextTabIndex('ArrowRight', 3, 4), 0);
  assert.equal(mod.nextTabIndex('ArrowLeft', 0, 4), 3);
  assert.equal(mod.nextTabIndex('Home', 2, 4), 0);
  assert.equal(mod.nextTabIndex('End', 0, 4), 3);
  assert.equal(mod.nextTabIndex('a', 0, 4), -1);
});

// A just-enough DOM to drive the element: tree, attributes, events, focus.
function fakeDom() {
  class Node {
    constructor(tag) {
      this.tag = tag; this.attrs = new Map(); this.children = []; this.listeners = {}; this.parent = null; this.textContent = '';
    }
    setAttribute(k, v) { this.attrs.set(k, String(v)); }
    getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
    removeAttribute(k) { this.attrs.delete(k); }
    get dataset() { return { client: this.getAttribute('data-client') }; }
    get id() { return this.getAttribute('id'); }
    append(...kids) { for (const k of kids) { k.parent = this; this.children.push(k); } }
    replaceChildren(...kids) { for (const c of this.children) c.parent = null; this.children = []; this.append(...kids); }
    addEventListener(t, fn) { (this.listeners[t] ??= []).push(fn); }
    closest(sel) { return sel === '[role="tab"]' && this.getAttribute('role') === 'tab' ? this : null; }
    focus() { dom.activeElement = this; }
    walk() { return [this, ...this.children.flatMap((c) => c.walk())]; }
    getElementById(id) { return this.walk().find((n) => n.id === id) ?? null; }
    querySelector(sel) { return this.walk().find((n) => sel === `.${n.getAttribute('class')}`) ?? null; }
    querySelectorAll() { return []; }
    isAttached(root) { for (let n = this; n; n = n.parent) if (n === root) return true; return false; }
  }
  const dom = { activeElement: null, Node };
  return dom;
}

async function mountElement(attrs = {}) {
  const dom = fakeDom();
  const defined = new Map();
  globalThis.document = { createElement: (t) => new dom.Node(t) };
  globalThis.HTMLElement = class extends dom.Node {
    constructor() { super('host'); this.isConnected = false; }
    attachShadow() { this.shadowRoot = new dom.Node('shadow'); return this.shadowRoot; }
  };
  globalThis.customElements = { get: (n) => defined.get(n), define: (n, c) => defined.set(n, c) };
  const mod = await import(`../catalyst-ai-install.js?fresh=${Math.random()}`);
  const host = new mod.default();
  for (const [k, v] of Object.entries(attrs)) host.setAttribute(k, v);
  return { dom, host };
}

const fire = (node, type, event) => node.listeners[type].forEach((fn) => fn(event));

test('a tab click updates in place: same tab nodes, focus stays on the tab (A1)', async () => {
  const { dom, host } = await mountElement();
  host.isConnected = true;
  host.connectedCallback();
  const tablist = host.shadowRoot.walk().find((n) => n.getAttribute('role') === 'tablist');
  const before = [...tablist.children];
  const codex = before.find((t) => t.dataset.client === 'codex');
  codex.focus();
  fire(tablist, 'click', { target: codex });
  assert.deepEqual(tablist.children, before, 'tablist children are the same nodes');
  assert.equal(dom.activeElement, codex);
  assert.ok(codex.isAttached(host.shadowRoot), 'focused tab is still in the tree');
  assert.equal(codex.getAttribute('aria-selected'), 'true');
  assert.equal(codex.getAttribute('tabindex'), '0');
  const others = before.filter((t) => t !== codex);
  assert.ok(others.every((t) => t.getAttribute('aria-selected') === 'false' && t.getAttribute('tabindex') === '-1'));
  assert.equal(host.shadowRoot.getElementById('panel').getAttribute('aria-labelledby'), 'tab-codex');

  let prevented = false;
  fire(tablist, 'keydown', { key: 'ArrowRight', target: codex, preventDefault: () => (prevented = true) });
  assert.ok(prevented);
  assert.equal(dom.activeElement.dataset.client, 'copilot-cli');
  assert.ok(dom.activeElement.isAttached(host.shadowRoot));
});

test('every code block is a labelled region (A2)', async () => {
  const { host } = await mountElement();
  host.isConnected = true;
  host.connectedCallback();
  const pres = host.shadowRoot.walk().filter((n) => n.tag === 'pre');
  assert.ok(pres.length > 0);
  for (const pre of pres) {
    assert.equal(pre.getAttribute('role'), 'region');
    assert.ok(pre.getAttribute('aria-label'));
    assert.equal(pre.getAttribute('tabindex'), '0');
  }
});

test('theme and variant never re-render; only a real client change does (A4)', async () => {
  const { host } = await mountElement();
  host.isConnected = true;
  host.connectedCallback();
  const panel = host.shadowRoot.getElementById('panel');
  const content = panel.children[0];
  host.attributeChangedCallback('theme', null, 'dark');
  host.attributeChangedCallback('variant', 'full', 'full');
  host.attributeChangedCallback('client', 'codex', 'codex');
  assert.equal(panel.children[0], content, 'no render for theme or an unchanged value');
  host.setAttribute('client', 'codex');
  host.attributeChangedCallback('client', null, 'codex');
  assert.notEqual(panel.children[0], content);
  assert.equal(host.client, 'codex');
});

test('no render before connection: upgrade renders once (A4)', async () => {
  const { host } = await mountElement({ client: 'vscode', theme: 'dark' });
  host.attributeChangedCallback('client', null, 'vscode');
  assert.equal(host.shadowRoot, undefined, 'nothing built before connectedCallback');
  host.isConnected = true;
  host.connectedCallback();
  assert.equal(host.client, 'vscode');
});

test('host variables override the palette in every theme (A3)', () => {
  const src = readFileSync(join(pkg, 'catalyst-ai-install.js'), 'utf8');
  assert.ok(src.includes('--catalyst-ai-code'));
  assert.ok(!/:host\(\[theme="light"\]\), :host\(\[theme="dark"\]\) \{\s*--fg/.test(src), 'no theme block that bypasses the host variables');
  const readmeText = readFileSync(join(pkg, 'README.md'), 'utf8');
  for (const v of ['fg', 'bg', 'muted', 'border', 'accent', 'code', 'font']) {
    assert.ok(readmeText.includes(`--catalyst-ai-${v}`), v);
  }
});
