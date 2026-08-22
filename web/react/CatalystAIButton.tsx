/**
 * React wrapper for the Catalyst AI split-button — for the Catalyst console.
 *
 * The console can do something the docs cannot: it knows who the user is, so it
 * bakes the real org and project into the setup instructions. That removes the
 * first "which project?" round trip from the very first prompt.
 *
 * The wrapper deliberately owns nothing but mount/unmount. All behaviour lives
 * in the vanilla component so docs, console and marketing site cannot drift.
 *
 *   import { CatalystAIButton } from './CatalystAIButton';
 *
 *   <CatalystAIButton
 *     preset="install"
 *     org={currentOrg.id}
 *     project={currentProject?.name ?? 'default'}
 *     onSelect={(id) => analytics.track('catalyst_ai_setup_clicked', { client: id })}
 *   />
 */
import { useEffect, useRef } from 'react';

// Side-effect import: registers window.CatalystAIButton and injects styles once.
import '../catalyst-ai-button.js';

export type CatalystAIPreset = 'ask' | 'install';

export interface CatalystAIButtonProps {
  /** `install` sets Catalyst up in a client; `ask` hands the current page to an assistant. */
  preset?: CatalystAIPreset;
  /** Organization ID, so the copied setup text carries real context. Console only. */
  org?: string | null;
  /** Project name — defaults to the auto-provisioned `default` when omitted. */
  project?: string | null;
  /** Override while the repo is private, or to pin a fork. */
  marketplace?: string;
  /** Follow the console's theme rather than the OS preference. */
  theme?: 'light' | 'dark';
  align?: 'left' | 'right';
  /** Fires with the entry id (`claude-code`, `codex`, `copilot`, `all`, …). */
  onSelect?: (id: string) => void;
  className?: string;
}

interface MountOptions extends Record<string, unknown> {
  preset?: string;
}

interface CatalystAIButtonGlobal {
  mount(host: HTMLElement, options?: MountOptions): { root: HTMLElement } | null;
}

declare global {
  interface Window {
    CatalystAIButton?: CatalystAIButtonGlobal;
  }
}

export function CatalystAIButton({
  preset = 'install',
  org = null,
  project = null,
  marketplace,
  theme,
  align = 'right',
  onSelect,
  className,
}: CatalystAIButtonProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  // Keep the latest callback without forcing a remount when it changes identity.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const host = hostRef.current;
    const api = typeof window !== 'undefined' ? window.CatalystAIButton : undefined;
    if (!host || !api) return;

    api.mount(host, {
      preset,
      org,
      project,
      marketplace,
      theme,
      align,
      onSelect: (id: string) => onSelectRef.current?.(id),
    });

    // The vanilla component appends a single root and guards against double
    // mounting, so unmount is just "drop what we appended" — which also makes
    // React 18 StrictMode's double-invoke harmless.
    return () => {
      host.replaceChildren();
      delete (host as HTMLElement & { __caiMounted?: boolean }).__caiMounted;
    };
  }, [preset, org, project, marketplace, theme, align]);

  return <div ref={hostRef} className={className} />;
}

export default CatalystAIButton;
