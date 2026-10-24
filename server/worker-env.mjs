// Compute and LaTeX processes receive OS/runtime settings, never service secrets.
const allowed = new Set([
  'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC',
  'TEMP', 'TMP', 'TMPDIR', 'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA',
  'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'VIRTUAL_ENV',
  'SSL_CERT_FILE', 'SSL_CERT_DIR',
]);
export function workerEnvironment(environment = process.env) {
  return Object.fromEntries(Object.entries(environment).filter(([name]) => allowed.has(name.toUpperCase())));
}

// Preserve the terminal's configured shell and SSH agent without inheriting API keys.
export function terminalEnvironment(environment = process.env) {
  const terminalAllowed = new Set(['SHELL', 'TERM', 'COLORTERM', 'SSH_AUTH_SOCK', 'SSH_AGENT_PID']);
  return { ...workerEnvironment(environment), ...Object.fromEntries(
    Object.entries(environment).filter(([name]) => terminalAllowed.has(name.toUpperCase()))),
  };
}
