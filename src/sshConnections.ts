// Saved SSH connections for the terminal panel. Only the command details are stored
// (in this browser's localStorage); passwords and 2FA codes are always typed at the prompt.

export type SshConnection = {
  id: string;
  label: string;
  user: string;
  host: string;
  port?: number;
  jumpHost?: string;
};

export type SshDraft = Omit<SshConnection, 'id'>;

const storageKey = 'pre.sshConnections';
const userPattern = /^[A-Za-z0-9._-]{1,64}$/;
const hostPattern = /^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,252}[A-Za-z0-9])?$/;
// A jump host may carry its own user and port, as in `ssh -J user@jump:2222 ...`.
const jumpPattern = /^(?:[A-Za-z0-9._-]{1,64}@)?[A-Za-z0-9](?:[A-Za-z0-9.-]{0,252}[A-Za-z0-9])?(?::\d{1,5})?$/;
// ssh flags that take a value (from `man ssh`), so the value isn't mistaken for the destination.
const flagsWithValue = new Set('BbcDEeFIiJLlmOoPpQRSWw'.split(''));

export const sshPresets: { label: string; host: string; jumpHost?: string }[] = [
  { label: 'Nittany AI Compute', host: 'nittanyaicompute.ist.psu.edu', jumpHost: 'ssh.ist.psu.edu' },
  { label: 'Roar Collab', host: 'submit.hpc.psu.edu' },
];

/** Returns an error message, or null if the draft is valid. */
export function validateSsh(draft: SshDraft): string | null {
  if (!draft.label.trim()) return 'Give the connection a name.';
  if (!userPattern.test(draft.user)) return 'Username may only contain letters, numbers, ".", "_" and "-".';
  if (!hostPattern.test(draft.host)) return 'Enter a host name like login.example.edu.';
  if (draft.jumpHost && !jumpPattern.test(draft.jumpHost)) return 'Enter a jump host like ssh.example.edu (or user@host:port).';
  if (draft.port !== undefined && !(Number.isInteger(draft.port) && draft.port >= 1 && draft.port <= 65535))
    return 'Port must be between 1 and 65535.';
  return null;
}

/** The ssh command line. Inputs are validated to safe characters, so no shell quoting is needed. */
export function sshCommand(connection: SshDraft): string {
  const parts = ['ssh'];
  if (connection.jumpHost) parts.push('-J', connection.jumpHost.includes('@') ? connection.jumpHost : `${connection.user}@${connection.jumpHost}`);
  if (connection.port && connection.port !== 22) parts.push('-p', String(connection.port));
  parts.push(`${connection.user}@${connection.host}`);
  return parts.join(' ');
}

export type ParsedSsh = { draft: Omit<SshDraft, 'label'>; ignored: string[] } | { error: string };

/** Split like a shell would for simple quoting ('a b', "a b"); no expansion. */
function tokenize(text: string): string[] {
  const tokens: string[] = [];
  let current = '', quote: string | null = null, started = false;
  for (const ch of text) {
    if (quote) { if (ch === quote) quote = null; else current += ch; continue; }
    if (ch === '"' || ch === "'") { quote = ch; started = true; continue; }
    if (/\s/.test(ch)) { if (started || current) tokens.push(current); current = ''; started = false; continue; }
    current += ch;
  }
  if (started || current) tokens.push(current);
  return tokens;
}

/** Read a pasted command like `ssh -J user@jump -p 2222 user@host` into connection fields.
 *  Options a saved connection can't represent are reported in `ignored`. */
export function parseSshCommand(text: string): ParsedSsh {
  let tokens = tokenize(text.trim().replace(/^(\$|>|PS [^>]*>)\s*/, ''));
  if (tokens[0]?.replace(/\.exe$/i, '').toLowerCase().endsWith('ssh')) tokens = tokens.slice(1);
  let user = '', host = '', port: number | undefined, jumpHost: string | undefined;
  const ignored: string[] = [];
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token.startsWith('-') && token.length > 1) {
      const flag = token[1];
      if (!flagsWithValue.has(flag)) { ignored.push(token); continue; } // e.g. -v, -A, -X
      const value = token.length > 2 ? token.slice(2) : tokens[++i];
      if (value === undefined) return { error: `${token} is missing its value.` };
      if (flag === 'p') port = Number(value);
      else if (flag === 'l') user = value;
      else if (flag === 'J') {
        if (value.includes(',')) return { error: 'Only one jump host is supported.' };
        jumpHost = value;
      } else ignored.push(`${token.length > 2 ? token : `${token} ${value}`}`);
      continue;
    }
    if (host) { ignored.push(token); continue; } // a remote command after the destination
    let destination = token;
    const uri = /^ssh:\/\/(?:([^@/]+)@)?([^:/]+)(?::(\d+))?\/?$/.exec(destination);
    if (uri) { if (uri[1]) user = uri[1]; host = uri[2]; if (uri[3]) port = Number(uri[3]); continue; }
    const at = destination.lastIndexOf('@');
    if (at !== -1) { user = destination.slice(0, at); destination = destination.slice(at + 1); }
    host = destination;
  }
  if (!host) return { error: 'Could not find a host. Paste something like: ssh user@host' };
  if (jumpHost && user && jumpHost === `${user}@${jumpHost.split('@').pop()}`) jumpHost = jumpHost.split('@').pop();
  const draft = { user, host, port: port === 22 ? undefined : port, jumpHost };
  const problem = validateSsh({ ...draft, label: host, user: user || 'placeholder' });
  if (problem) return { error: problem };
  return { draft, ignored };
}

/** A friendly default name for a host: a matching preset, else the host itself. */
export function defaultLabel(host: string): string {
  return sshPresets.find(p => p.host === host)?.label ?? host;
}

export function loadSshConnections(): SshConnection[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey) || '[]');
    return Array.isArray(parsed) ? parsed.filter(c => c && typeof c.id === 'string' && !validateSsh(c)) : [];
  } catch {
    return [];
  }
}

export function saveSshConnections(connections: SshConnection[]): void {
  try { localStorage.setItem(storageKey, JSON.stringify(connections)); } catch { /* storage unavailable */ }
}
