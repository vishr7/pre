import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { Runtime, safePath } from './runtime.mjs';
async function setup(t, options) {
 const root = await mkdtemp(path.join(tmpdir(), 'pre-test-'));
 const runtime = new Runtime({ root, ...options });
 t.after(async () => { await runtime.close(); await rm(root, {recursive:true, force:true}); });
 return runtime;
}
const args = (code, language = 'python', sessionId = 'test') => ({ code, language, sessionId, files: [] });
test('Python preserves state, returns expressions, separates errors, and isolates sessions', async t => {
 const r = await setup(t);
 assert.equal((await r.execute(args('value = 21\nprint("ready")'))).stdout, 'ready\n');
 const result = await r.execute(args('value * 2'));
 assert.equal(result.stdout, '42\n'); assert.equal(result.executionCount, 2);
 const error = await r.execute(args('print("before")\n1 / 0'));
 assert.equal(error.stdout, 'before\n'); assert.match(error.error, /ZeroDivisionError/);
 assert.match((await r.execute(args('value', 'python', 'other'))).error, /NameError/);
 assert.equal((await r.execute(args('value'))).stdout, '21\n');
 await r.reset({sessionId:'test'});
 assert.match((await r.execute(args('value'))).error, /NameError/);
});
test('JavaScript persists state and reports exceptions', async t => {
 const r = await setup(t);
 assert.equal((await r.execute(args('var value = 7; console.log("ready");', 'javascript'))).stdout, 'ready\n');
 assert.equal((await r.execute(args('value * 6', 'javascript'))).stdout, '42\n');
 assert.match((await r.execute(args('throw new Error("oops")', 'javascript'))).error, /oops/);
 assert.equal((await r.execute(args('Promise.resolve(value + 1)', 'javascript'))).stdout, '8\n');
});
test('Project files are importable and traversal is rejected', async t => {
 const r = await setup(t);
 const result = await r.execute({...args('from helper import answer\nanswer'), files:[{path:'src/helper.py',content:'answer = 42'}]});
 assert.equal(result.stdout, '42\n');
 assert.throws(() => safePath('/tmp/project', '../escape'), /inside/);
 await assert.rejects(r.execute({...args('1'), files:[{path:'../../escape', content:'bad'}]}), /inside/);
});
test('Timeout resets an infinite kernel and the next cell can run', async t => {
 const r = await setup(t, {timeout:500});
 await assert.rejects(r.execute(args('while True: pass')), /timed out/);
 assert.equal((await r.execute(args('40 + 2'))).stdout, '42\n');
});
test('Stop interrupts a running cell and rejects concurrent execution', async t => {
 const r = await setup(t);
 const pending = r.execute(args('import time\ntime.sleep(20)'));
 const rejection = assert.rejects(pending, /stopped/);
 await new Promise(resolve => setTimeout(resolve, 100));
 await assert.rejects(r.execute(args('1')), /already running/);
 await r.reset({sessionId:'test'}); await rejection;
 assert.equal((await r.execute(args('1 + 1'))).stdout, '2\n');
});
test('Matplotlib returns real PNG output', {skip: !process.env.PRE_TEST_PLOTS}, async t => {
 const r = await setup(t);
 const result = await r.execute(args('import matplotlib.pyplot as plt\nplt.plot([1, 2, 3], [1, 4, 9])\nplt.show()'));
 assert.equal(result.error, undefined);
 assert.match(result.images[0], /^data:image\/png;base64,iVBOR/);
});
test('LaTeX compiles a cell into an actual PDF', {skip: !process.env.PRE_TEST_LATEX}, async t => {
 const r = await setup(t);
 const result = await r.compile({sessionId:'test',source:'\\section{Test}\nHello $x^2$.',files:[]});
 const id = result.pdfUrl.split('/').pop();
 assert.equal(r.pdfs.get(id).subarray(0,4).toString(), '%PDF');
 await assert.rejects(r.compile({sessionId:'test',source:'\\thiscommanddoesnotexist',files:[]}), /Undefined control sequence/);
});
test('Simultaneous first cells share one session lock', async t => {
 const r = await setup(t);
 const pending = r.execute(args('import time\ntime.sleep(0.1)\n42'));
 await assert.rejects(r.execute(args('24')), /already running/);
 assert.equal((await pending).stdout, '42\n');
});
test('Leaving a project releases its kernel and session', async t => {
 const r = await setup(t);
 await r.execute(args('value = 10'));
 await r.release({sessionId:'test'});
 assert.equal(r.sessions.size,0);
 assert.match((await r.execute(args('value'))).error,/NameError/);
});
