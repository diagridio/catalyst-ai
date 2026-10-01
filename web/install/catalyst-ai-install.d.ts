export interface InstallItem {
  /** Stable id within a client, sent as `detail.item` on copy. */
  id: string;
  label: string;
  lang: 'bash' | 'json' | 'text';
  /** The exact text placed on the clipboard. */
  text: string;
}

export interface InstallStep {
  id: string;
  title: string;
  description: string;
  items: InstallItem[];
}

export interface InstallClient {
  id: 'claude-code' | 'codex' | 'copilot-cli' | 'vscode' | (string & {});
  label: string;
  steps: InstallStep[];
}

export interface InstallCommand {
  id: string;
  /** For example `/catalyst-ai:try-workflow`. */
  name: string;
  description: string;
  /** The command body, offered as a paste-in prompt where there is no slash command. */
  prompt: string;
}

export interface InstallData {
  schema: number;
  mcpUrl: string;
  commands: InstallCommand[];
  clients: InstallClient[];
}

export interface CatalystAiInstallCopyDetail {
  client: string;
  item: string;
  /** The element's `source` attribute, or an empty string. */
  source: string;
}

export const installData: InstallData;

export function resolveClient(clients: InstallClient[], wanted?: string | null): InstallClient;
export function nextTabIndex(key: string, index: number, count: number): number;

export class CatalystAiInstallElement extends HTMLElement {
  /** The selected tab id. Setting it selects that tab. */
  client: string;
  /** Free text echoed in the copy event: docs, console, website or your own. */
  source: string;
}

export default CatalystAiInstallElement;

declare global {
  interface HTMLElementTagNameMap {
    'catalyst-ai-install': CatalystAiInstallElement;
  }
  interface HTMLElementEventMap {
    'catalyst-ai-install:copy': CustomEvent<CatalystAiInstallCopyDetail>;
  }
}
