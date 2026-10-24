import { test } from 'node:test';
import assert from 'node:assert/strict';
import { workerEnvironment, terminalEnvironment } from './worker-env.mjs';

test('worker environment preserves OS settings and excludes all application credentials', () => {
  const result = workerEnvironment({ Path: 'runtime-path', SystemRoot: 'windows',
    GEMINI_API_KEY: 'dummy', DATABASE_URL: 'dummy', S3_SECRET_ACCESS_KEY: 'dummy',
    UNKNOWN_SERVICE_TOKEN: 'dummy', NODE_OPTIONS: 'dummy', PYTHONPATH: 'dummy' });
  assert.deepEqual(result, { Path: 'runtime-path', SystemRoot: 'windows' });
});

test('terminal preserves shell and SSH-agent configuration without service secrets', () => {
  const environment = { PATH: '/bin', SHELL: '/bin/zsh', SSH_AUTH_SOCK: '/tmp/agent.sock',
    SSH_AGENT_PID: '123', GEMINI_API_KEY: 'dummy', DATABASE_URL: 'dummy',
    S3_SECRET_ACCESS_KEY: 'dummy', RUNNER_SERVICE_TOKEN: 'dummy' };
  assert.deepEqual(terminalEnvironment(environment), { PATH: '/bin', SHELL: '/bin/zsh',
    SSH_AUTH_SOCK: '/tmp/agent.sock', SSH_AGENT_PID: '123' });
  assert.equal(workerEnvironment(environment).SSH_AUTH_SOCK, undefined);
});
