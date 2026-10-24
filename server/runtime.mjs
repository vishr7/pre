import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, writeFile, readFile, rm, lstat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
const projectRoot = fileURLToPath(new URL('../', import.meta.url));
const workerRoot = fileURLToPath(new URL('./', import.meta.url));
export function safePath(root, name) {
  if (typeof name !== 'string' || !name || name.includes('\\') || name.includes('\0')) throw new Error('Invalid project file path.');
  const resolved = path.resolve(root, name);
  if (!resolved.startsWith(root + path.sep)) throw new Error('Project files must stay inside the workspace.');
  return resolved;
}
async function writeFiles(root, files = []) {
  if (!Array.isArray(files) || files.length > 200) throw new Error('Expected at most 200 project files.');
  for (const file of files) {
    if (typeof file.content !== 'string' || file.content.length > 2000000) throw new Error('Project files must be text under 2 MB.');
    const target = safePath(root, file.path);
    // Python may create symlinks: never follow them when synchronizing uploaded files.
    let part = root;
    for (const segment of path.relative(root, target).split(path.sep)) {
      part = path.join(part, segment);
      const stat = await lstat(part).catch(() => null);
      if (stat?.isSymbolicLink()) throw new Error('Project file paths cannot contain symbolic links.');
    }
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, file.content);
  }
}
export class Runtime {
  constructor({ root = path.join(projectRoot, '.runtime'), timeout = 30000 } = {}) {
    this.root = root; this.timeout = timeout; this.sessions = new Map(); this.pdfs = new Map();
    this.python = process.env.PRE_PYTHON || (existsSync(path.join(projectRoot, '.venv/bin/python')) ? path.join(projectRoot, '.venv/bin/python') : 'python3');
    this.tectonic = process.env.PRE_TECTONIC || (existsSync(path.join(projectRoot, '.runtime/bin/tectonic')) ? path.join(projectRoot, '.runtime/bin/tectonic') : 'tectonic');
  }
  async session(id) {
    if (typeof id !== 'string' || !/^[\w-]{1,80}$/.test(id)) throw new Error('A valid sessionId is required.');
    if (!this.sessions.has(id)) {
      if (this.sessions.size >= 16) throw new Error('Too many kernels. Restart the local server to release unused sessions.');
      // Register before awaiting directory creation so concurrent requests share the same lock.
      const dir = mkdir(this.root, { recursive: true }).then(() => mkdtemp(path.join(this.root, 'session-')));
      const session = { workers: {}, running: false, compile: null, dir };
      this.sessions.set(id, session);
    }
    const session = this.sessions.get(id);
    session.directory = await session.dir;
    return session;
  }
  worker(session, language) {
    if (session.workers[language]) return session.workers[language];
    const python = language === 'python';
    const child = spawn(python ? this.python : process.execPath, [path.join(workerRoot, python ? 'python-worker.py' : 'javascript-worker.mjs')], {
      cwd: session.directory, stdio: ['pipe', 'ignore', 'pipe', 'pipe'], detached: process.platform !== 'win32',
      env: { ...process.env, PYTHONUNBUFFERED: '1', MPLBACKEND: 'Agg', MPLCONFIGDIR: path.join(session.directory, '.matplotlib') },
    });
    const worker = { child, pending: null, buffer: '', errors: '', count: 0 };
    session.workers[language] = worker;
    child.stderr.on('data', chunk => { worker.errors = (worker.errors + chunk).slice(-5000); });
    child.stdin.on('error', () => {});
    child.stdio[3].on('data', chunk => {
      worker.buffer += chunk;
      if (worker.buffer.length > 15000000) { this.kill(child); worker.pending?.reject(new Error('Cell output exceeded 15 MB; kernel restarted.')); return; }
      const newline = worker.buffer.indexOf('\n');
      if (newline !== -1 && worker.pending) {
        try { worker.pending.resolve({ ...JSON.parse(worker.buffer.slice(0, newline)), executionCount: ++worker.count }); }
        catch { worker.pending.reject(new Error('Invalid kernel response. Restart the runtime.')); }
        worker.buffer = worker.buffer.slice(newline + 1);
      }
    });
    const failed = message => {
      if (session.workers[language] === worker) delete session.workers[language];
      worker.pending?.reject(new Error(message));
    };
    child.on('error', error => failed(`Could not start ${language}: ${error.message}`));
    child.on('exit', () => failed(`Kernel stopped. ${worker.errors}`));
    return worker;
  }
  kill(child) { try { if (process.platform === 'win32') child.kill('SIGKILL'); else process.kill(-child.pid, 'SIGKILL'); } catch {} }
  async execute({ sessionId, language, code, files }) {
    if (!['python', 'javascript'].includes(language)) throw new Error('Supported executable languages: python, javascript.');
    if (typeof code !== 'string' || code.length > 200000) throw new Error('Code must be text under 200 KB.');
    const session = await this.session(sessionId);
    if (session.running) throw new Error('This notebook is already running a cell.');
    session.running = true;
    try {
      await writeFiles(session.directory, files);
      const worker = this.worker(session, language);
      return await new Promise((resolve, reject) => {
        const finish = callback => value => { clearTimeout(timer); worker.pending = null; callback(value); };
        const timer = setTimeout(() => {
          delete session.workers[language]; this.kill(worker.child);
          worker.pending?.reject(new Error('Execution timed out. The kernel was reset; run earlier cells again.'));
        }, this.timeout);
        worker.pending = { resolve: finish(resolve), reject: finish(reject) };
        worker.child.stdin.write(JSON.stringify({ code }) + '\n');
      });
    } finally { session.running = false; }
  }
  async reset({ sessionId }) {
    const session = this.sessions.get(sessionId);
    if (!session) return { ok: true };
    for (const worker of Object.values(session.workers)) {
      worker.pending?.reject(new Error('Execution stopped. Kernel variables have been cleared.'));
      this.kill(worker.child);
    }
    session.workers = {};
    if (session.compile) { this.kill(session.compile); session.compile = null; }
    return { ok: true };
  }
  async compile({ sessionId, source, files, entrypoint = 'paper/main.tex' }) {
    const session = await this.session(sessionId);
    if (session.running) throw new Error('This notebook is already running a cell.');
    session.running = true;
    let dir;
    try {
      dir = await mkdtemp(path.join(this.root, 'latex-'));
      await writeFiles(dir, files);
      let input;
      if (source !== undefined) {
        if (typeof source !== 'string' || source.length > 200000) throw new Error('LaTeX must be text under 200 KB.');
        input = path.join(dir, 'cell.tex');
        const document = /\\documentclass(?:\[|\{)/.test(source) ? source : `\\documentclass{article}\n\\usepackage{amsmath,amssymb,graphicx}\n\\begin{document}\n${source}\n\\end{document}\n`;
        await writeFile(input, document);
      } else input = safePath(dir, entrypoint);
      const output = path.join(dir, 'output'); await mkdir(output);
      const logs = await new Promise((resolve, reject) => {
        const child = spawn(this.tectonic, ['--untrusted', '--keep-logs', '--outdir', output, input], { cwd: dir, detached: process.platform !== 'win32', env: { ...process.env, TECTONIC_UNTRUSTED_MODE: '1' } });
        session.compile = child;
        let log = '';
        const collect = data => { log = (log + data).slice(-100000); };
        child.stdout.on('data', collect); child.stderr.on('data', collect);
        const timer = setTimeout(() => { this.kill(child); reject(new Error('LaTeX compilation timed out after 90 seconds.')); }, 90000);
        child.on('error', error => { clearTimeout(timer); reject(new Error(error.code === 'ENOENT' ? 'Tectonic is not installed. Run npm run setup:latex, then compile again.' : error.message)); });
        child.on('exit', code => { clearTimeout(timer); code === 0 ? resolve(log) : reject(new Error(log || 'LaTeX compilation stopped.')); });
      });
      const pdf = await readFile(path.join(output, path.basename(input, '.tex') + '.pdf'));
      const id = randomUUID();
      if (this.pdfs.size >= 30) this.pdfs.delete(this.pdfs.keys().next().value);
      this.pdfs.set(id, pdf);
      return { pdfUrl: `/api/pdf/${id}`, logs };
    } finally { session.running = false; session.compile = null; if (dir) await rm(dir, { recursive: true, force: true }); }
  }
  async close() {
    for (const [sessionId, session] of this.sessions) { await this.reset({ sessionId }); await rm(await session.dir, { recursive: true, force: true }); }
    this.sessions.clear(); this.pdfs.clear();
  }
}
export function runtimePlugin() {
  const runtime = new Runtime();
  function attach(server) {
    server.httpServer?.once('close', () => void runtime.close());
    server.middlewares.use(async (req, res, next) => {
      if (!req.url?.startsWith('/api/')) return next();
      const send = (status, body) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(body)); };
      const host = req.headers.host || '';
      if (!/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host)) return send(403, { error: 'The local runtime accepts loopback connections only.' });
      if (req.headers.origin && req.headers.origin !== `http://${host}`) return send(403, { error: 'Cross-origin execution is blocked.' });
      if (req.method === 'GET' && req.url.startsWith('/api/pdf/')) {
        const pdf = runtime.pdfs.get(req.url.slice('/api/pdf/'.length));
        if (!pdf) return send(404, { error: 'PDF expired. Compile again.' });
        res.writeHead(200, { 'Content-Type': 'application/pdf', 'Content-Length': pdf.length, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' }); return res.end(pdf);
      }
      if (req.method !== 'POST' || req.headers['x-pre-runtime'] !== '1' || !req.headers['content-type']?.startsWith('application/json')) return send(403, { error: 'Expected a same-origin PRE request.' });
      try {
        let raw = '';
        for await (const chunk of req) { raw += chunk; if (raw.length > 5000000) return send(413, { error: 'Project request exceeds 5 MB.' }); }
        const data = JSON.parse(raw);
        if (req.url === '/api/execute') return send(200, await runtime.execute(data));
        if (req.url === '/api/compile') return send(200, await runtime.compile(data));
        if (req.url === '/api/runtime/reset') return send(200, await runtime.reset(data));
        return send(501, { error: 'AI tools require an AI backend. Configure its URL in Settings.' });
      } catch (error) { return send(400, { error: error.message }); }
    });
  }
  return { name: 'pre-local-runtime', configureServer: attach, configurePreviewServer: attach };
}
