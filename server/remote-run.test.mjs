import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { RemoteCapture, cleanTerminalText, remoteRunCommand, validInterpreter } from '../src/remoteRun.ts';

const hasBash = spawnSync('bash', ['-c', 'command -v mktemp base64'], { encoding: 'utf8' }).status === 0;

function runInBash(code, interpreter = 'node') {
  const command = remoteRunCommand(code, 'abc123', interpreter);
  const result = spawnSync('bash', ['-c', command], { encoding: 'utf8' });
  const capture = new RemoteCapture('abc123');
  // Feed in small chunks, like a terminal stream; also include the echoed command first.
  const stream = command + '\r\n' + result.stdout + result.stderr;
  let done = null;
  for (let i = 0; i < stream.length && !done; i += 7) done = capture.feed(stream.slice(i, i + 7));
  return done;
}

test('runs code in a real shell and captures output and exit code', { skip: !hasBash }, () => {
  const code = 'const s = "quotes \' \\" $HOME `x` \\\\ ünïcode";\nconsole.log(s);\nconsole.log(6 * 7);';
  assert.deepEqual(runInBash(code), { output: 'quotes \' " $HOME `x` \\ ünïcode\n42\n', exitCode: 0 });
  assert.deepEqual(runInBash('process.stdout.write("no newline")'), { output: 'no newline', exitCode: 0 });
  const failed = runInBash('console.log("before"); process.exit(3)');
  assert.equal(failed.exitCode, 3);
  assert.match(failed.output, /before/);
  const missing = runInBash('print(1)', 'definitely-not-an-interpreter');
  assert.equal(missing.exitCode, 127);
});

test('echoed command never counts as a marker; terminal escapes are removed', () => {
  const capture = new RemoteCapture('id1');
  assert.equal(capture.feed(remoteRunCommand('print(1)', 'id1', 'python3') + '\r\n'), null);
  const result = capture.feed('\r\n__PRE_BEGIN_id1__\r\n\x1b[32mhello\x1b[0m\x1b[3Cworld\r\n\x1b]0;title\x07\r\n__PRE_END_id1__ 0\r\n');
  assert.deepEqual(result, { output: 'hello   world\n', exitCode: 0 });
  assert.equal(cleanTerminalText('a\r\r\nb\x1b[?25lc'), 'a\nbc');
});

test('reports a failure before the code started', () => {
  const capture = new RemoteCapture('x');
  assert.match(capture.feed('mktemp: command not found\r\n__PRE_END_x__ 127\r\n').output, /POSIX shell/);
});

test('interpreter setting accepts paths and simple wrappers only', () => {
  for (const ok of ['python3', '~/venvs/torch/bin/python', 'conda run -n my-env python', 'node'])
    assert.ok(validInterpreter(ok), ok);
  for (const bad of ['', 'python3; rm -rf ~', 'python $(id)', 'py|sh', 'python3 && x', ' python'])
    assert.ok(!validInterpreter(bad), bad);
});
