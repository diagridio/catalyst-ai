# @diagrid/catalyst-ai-install

`<catalyst-ai-install>`: install steps for [Diagrid Catalyst](https://diagrid.io) AI, one tab
per client (Claude Code, Codex, Copilot CLI, VS Code), with a copy button on every step.
Vanilla custom element, Shadow DOM, no dependencies, no network calls.

```html
<script type="module" src="https://cdn.jsdelivr.net/npm/@diagrid/catalyst-ai-install@0.1.0/catalyst-ai-install.js"></script>
<catalyst-ai-install source="website"></catalyst-ai-install>
```

Or `npm install @diagrid/catalyst-ai-install` and `import '@diagrid/catalyst-ai-install'`.

## Attributes

| attribute | values | default |
| --- | --- | --- |
| `variant` | `compact`, `full` | `full` |
| `client` | `claude-code`, `codex`, `copilot-cli`, `vscode` | `claude-code` |
| `theme` | `auto`, `light`, `dark` | `auto` |
| `source` | any text, echoed in the copy event (`docs`, `console`, `website`) | empty |

`theme="auto"` reads `--catalyst-ai-fg`, `--catalyst-ai-bg`, `--catalyst-ai-muted`,
`--catalyst-ai-border`, `--catalyst-ai-accent` and `--catalyst-ai-font` from the host page,
and falls back to `prefers-color-scheme`.

## Copy event

A successful copy dispatches a bubbling, composed `catalyst-ai-install:copy` event with
`detail: { client, item, source }`. When the clipboard is unavailable the text is selected
instead and no event is sent.

```js
document.addEventListener('catalyst-ai-install:copy', (e) => console.log(e.detail));
```

## Data

The steps are generated from the repository's `commands/` and README and shipped as
`install.json` and `data.js`. They are imported at build time; nothing is fetched.
