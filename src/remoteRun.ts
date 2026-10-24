// Run a notebook cell on the machine the terminal is SSH'd into, reusing that logged-in session.
// The code travels base64-encoded on one line (no quoting issues), is written to a temp file and
// run there, and begin/end markers in the output let us capture stdout/stderr and the exit code.

export type RemoteLanguage = 'python' | 'javascript';
export type RemoteResult = { output: string; exitCode: number | null; cancelled?: boolean };
export type RemoteRunner = {
  run(code: string, language: RemoteLanguage): Promise<RemoteResult>;
  activeTitle(): string; // name of the terminal tab the cell will run in
};
export type Interpreters = Record<RemoteLanguage, string>;

const storageKey = 'pre.remoteInterpreters';
export const defaultInterpreters: Interpreters = { python: 'python3', javascript: 'node' };
// e.g. python3, ~/venvs/torch/bin/python, conda run -n myenv python
const interpreterPattern = /^[A-Za-z0-9_./~+-]+(?: [A-Za-z0-9_./~+=-]+)*$/;
export const maxRemoteCodeBytes = 256 * 1024;

export function validInterpreter(value: string): boolean {
  return interpreterPattern.test(value) && value.length <= 200;
}

function base64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** One POSIX shell line (bash/zsh/sh). Markers are split with quotes so the echoed command never matches. */
export function remoteRunCommand(code: string, id: string, interpreter: string): string {
  const begin = `"__PRE_""BEGIN_${id}__"`, end = `"__PRE_""END_${id}__"`;
  const tmp = '"${TMPDIR:-/tmp}/pre-XXXXXX"';
  // Leading space keeps the line out of shell history where HISTCONTROL=ignorespace.
  return ` __pre_f=$(mktemp ${tmp}) && printf '%s' '${base64(code)}' | base64 -d > "$__pre_f"`
    + ` && printf '\\n%s\\n' ${begin} && ${interpreter} "$__pre_f"`
    + `; printf '\\n%s %s\\n' ${end} "$?"; rm -f "$__pre_f"`;
}

/** Remove terminal control sequences, keeping the text a user would see. */
export function cleanTerminalText(text: string): string {
  return text
    .replace(/\x1b\[(\d*)C/g, (_, n) => ' '.repeat(Number(n) || 1)) // cursor-forward used as spacing
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '')              // OSC (window titles etc.)
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')                        // CSI (colors, cursor moves)
    .replace(/\x1b[()][0-9A-Za-z]|\x1b[=>78]/g, '')
    .replace(/\r+\n/g, '\n').replace(/\r/g, '');
}

/** Accumulates terminal output for one run and reports the result once the end marker appears. */
export class RemoteCapture {
  private raw = '';
  readonly id: string;
  constructor(id: string) { this.id = id; }

  /** True once the code has started on the remote machine (or failed trying). */
  get started(): boolean {
    return this.raw.includes(`__PRE_BEGIN_${this.id}__`) || this.raw.includes(`__PRE_END_${this.id}__`);
  }

  feed(chunk: string): RemoteResult | null {
    this.raw += chunk;
    if (!this.raw.includes(`__PRE_END_${this.id}__`)) return null;
    const text = cleanTerminalText(this.raw);
    // Require the trailing newline: output can arrive mid-number ("1" then "27").
    const end = new RegExp(`\\n?__PRE_END_${this.id}__ (\\d+)\\n`).exec(text);
    if (!end) return null;
    const beginMarker = `__PRE_BEGIN_${this.id}__\n`;
    const begin = text.indexOf(beginMarker);
    const exitCode = Number(end[1]);
    if (begin === -1 || begin > end.index) {
      return { output: 'Could not prepare the code on the remote machine (it needs a POSIX shell with mktemp and base64).', exitCode };
    }
    return { output: text.slice(begin + beginMarker.length, end.index), exitCode };
  }
}

export function loadInterpreters(): Interpreters {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    return {
      python: typeof saved.python === 'string' && validInterpreter(saved.python) ? saved.python : defaultInterpreters.python,
      javascript: typeof saved.javascript === 'string' && validInterpreter(saved.javascript) ? saved.javascript : defaultInterpreters.javascript,
    };
  } catch {
    return { ...defaultInterpreters };
  }
}

export function saveInterpreters(value: Interpreters): void {
  try { localStorage.setItem(storageKey, JSON.stringify(value)); } catch { /* storage unavailable */ }
}
