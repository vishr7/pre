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
  const terminalAllowed = new Set(['SHELL', 'TERM', 'COLORTERM', 'SSH_AUTH_SOCK', 'SSH_AGENT_PID',
    // Windows: what PowerShell and OpenSSH need to find the user profile (~/.ssh) and programs.
    'USERNAME', 'USERDOMAIN', 'COMPUTERNAME', 'HOMEDRIVE', 'HOMEPATH', 'SYSTEMDRIVE', 'PROGRAMDATA',
    'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432', 'COMMONPROGRAMFILES', 'ALLUSERSPROFILE',
    'PSMODULEPATH', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'OS', 'PRE_TERMINAL_SHELL']);
  return { ...workerEnvironment(environment), ...Object.fromEntries(
    Object.entries(environment).filter(([name]) => terminalAllowed.has(name.toUpperCase()))),
  };
}
