import vm from 'node:vm';
import { createInterface } from 'node:readline';
import { createWriteStream } from 'node:fs';
import { format } from 'node:util';
const protocol = createWriteStream(null, { fd: 3 });
let stdout = '', stderr = '';
const append = (which, args) => {
  const text = format(...args) + '\n';
  if (which === 'stdout') stdout = (stdout + text).slice(0, 100000);
  else stderr = (stderr + text).slice(0, 100000);
};
const context = vm.createContext({
  console: { log: (...a) => append('stdout', a), info: (...a) => append('stdout', a), warn: (...a) => append('stderr', a), error: (...a) => append('stderr', a), table: (...a) => append('stdout', a) },
  setTimeout, clearTimeout, URL, TextEncoder, TextDecoder,
});
for await (const line of createInterface({ input: process.stdin })) {
  const start = performance.now(); stdout = ''; stderr = '';
  const result = {};
  try {
    const { code } = JSON.parse(line);
    const value = await new vm.Script(code, { filename: 'cell.js' }).runInContext(context, { timeout: 30000 });
    if (value !== undefined) append('stdout', [value]);
  } catch (error) { result.error = error.stack || String(error); }
  protocol.write(JSON.stringify({ ...result, stdout, stderr, images: [], durationMs: Math.round(performance.now() - start) }) + '\n');
}
