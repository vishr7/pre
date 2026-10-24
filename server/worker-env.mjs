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
