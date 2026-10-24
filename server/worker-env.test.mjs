import { test } from 'node:test';
import assert from 'node:assert/strict';
import { workerEnvironment } from './worker-env.mjs';

test('worker environment preserves OS settings and excludes all application credentials', () => {
  const result = workerEnvironment({ Path: 'runtime-path', SystemRoot: 'windows',
    GEMINI_API_KEY: 'dummy', DATABASE_URL: 'dummy', S3_SECRET_ACCESS_KEY: 'dummy',
    UNKNOWN_SERVICE_TOKEN: 'dummy', NODE_OPTIONS: 'dummy', PYTHONPATH: 'dummy' });
  assert.deepEqual(result, { Path: 'runtime-path', SystemRoot: 'windows' });
});
