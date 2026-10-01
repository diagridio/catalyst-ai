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
