import test from 'node:test';
import assert from 'node:assert/strict';
import { sshCommand, validateSsh, loadSshConnections, saveSshConnections, parseSshCommand, defaultLabel } from '../src/sshConnections.ts';

const base = { label: 'Lab', user: 'abc1234', host: 'nittanyaicompute.ist.psu.edu' };

test('builds ssh commands with optional jump host and port', () => {
  assert.equal(sshCommand(base), 'ssh abc1234@nittanyaicompute.ist.psu.edu');
  assert.equal(sshCommand({ ...base, jumpHost: 'ssh.ist.psu.edu' }),
    'ssh -J abc1234@ssh.ist.psu.edu abc1234@nittanyaicompute.ist.psu.edu');
  assert.equal(sshCommand({ ...base, port: 2222 }), 'ssh -p 2222 abc1234@nittanyaicompute.ist.psu.edu');
  assert.equal(sshCommand({ ...base, port: 22 }), 'ssh abc1234@nittanyaicompute.ist.psu.edu');
});

test('rejects anything that could inject shell syntax or is incomplete', () => {
  assert.equal(validateSsh(base), null);
  for (const bad of [
    { ...base, label: ' ' }, { ...base, user: 'a b' }, { ...base, user: 'a;rm -rf ~' }, { ...base, user: '$(id)' },
    { ...base, host: 'host.edu; whoami' }, { ...base, host: '-oProxyCommand=calc' }, { ...base, host: '' },
    { ...base, jumpHost: 'jump|sh' }, { ...base, port: 0 }, { ...base, port: 70000 }, { ...base, port: 1.5 },
  ]) assert.notEqual(validateSsh(bad), null, JSON.stringify(bad));
});

test('storage round-trips valid connections and drops tampered ones', () => {
  const store = new Map();
  globalThis.localStorage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  try {
    saveSshConnections([{ id: '1', ...base }]);
    assert.deepEqual(loadSshConnections(), [{ id: '1', ...base }]);
    store.set('pre.sshConnections', JSON.stringify([{ id: '2', ...base, host: 'x;rm' }, { id: '3', ...base }]));
    assert.deepEqual(loadSshConnections().map(c => c.id), ['3']);
    store.set('pre.sshConnections', 'not json');
    assert.deepEqual(loadSshConnections(), []);
  } finally {
    delete globalThis.localStorage;
  }
});

test('parses pasted ssh commands into connection fields', () => {
  const ws = { user: 'abc1234', host: 'nittanyaicompute.ist.psu.edu', port: undefined, jumpHost: 'ssh.ist.psu.edu' };
  assert.deepEqual(parseSshCommand('ssh -J abc1234@ssh.ist.psu.edu abc1234@nittanyaicompute.ist.psu.edu'), { draft: ws, ignored: [] });
  assert.deepEqual(parseSshCommand('$ ssh -J abc1234@ssh.ist.psu.edu abc1234@nittanyaicompute.ist.psu.edu').draft, ws);
  assert.deepEqual(parseSshCommand('PS C:\\Users\\me> ssh.exe abc1234@submit.hpc.psu.edu').draft,
    { user: 'abc1234', host: 'submit.hpc.psu.edu', port: undefined, jumpHost: undefined });
  assert.deepEqual(parseSshCommand('ssh -p 2222 -l bob lab.example.edu').draft,
    { user: 'bob', host: 'lab.example.edu', port: 2222, jumpHost: undefined });
  assert.deepEqual(parseSshCommand('ssh -p22 bob@lab.example.edu').draft.port, undefined);
  assert.deepEqual(parseSshCommand('ssh://bob@lab.example.edu:2200').draft, { user: 'bob', host: 'lab.example.edu', port: 2200, jumpHost: undefined });
  assert.equal(parseSshCommand('abc@host.edu').draft.host, 'host.edu');                  // no "ssh" prefix
  assert.equal(parseSshCommand('ssh -J alice@jump.edu:2222 bob@host.edu').draft.jumpHost, 'alice@jump.edu:2222');
  const extra = parseSshCommand('ssh -v -A -i ~/.ssh/id_ed25519 -o ServerAliveInterval=30 bob@host.edu nvidia-smi');
  assert.equal(extra.draft.host, 'host.edu');
  assert.deepEqual(extra.ignored, ['-v', '-A', '-i ~/.ssh/id_ed25519', '-o ServerAliveInterval=30', 'nvidia-smi']);
  assert.equal(sshCommand({ label: 'x', ...parseSshCommand('ssh -J abc@j.edu abc@h.edu').draft }), 'ssh -J abc@j.edu abc@h.edu');
});

test('reports unparseable or unsafe pastes', () => {
  for (const bad of ['', 'ssh', 'ssh -p', 'ssh -J a.edu,b.edu bob@h.edu', 'ssh bob@host.edu;rm', 'ssh -p 99999 bob@h.edu', 'ssh "bob smith"@h.edu'])
    assert.ok('error' in parseSshCommand(bad), bad);
  assert.equal(defaultLabel('nittanyaicompute.ist.psu.edu'), 'Nittany AI Compute');
  assert.equal(defaultLabel('lab.example.edu'), 'lab.example.edu');
});
