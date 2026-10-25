import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {batchCell,sshOnly} from '../src/iterateBatch.ts';
import {workerEnvironment} from './worker-env.mjs';
test('portable batch runs measured trials and excludes failures from ranking',()=>{
 const code='def run_trial(p):\n    if p["x"] == 9: raise ValueError("bad trial")\n    return {"loss": (p["x"]-2)**2}';
 const result=execFileSync('python3',['-c',batchCell(code,[{x:0},{x:2},{x:9}],'loss','minimize',2)],{env:workerEnvironment(),encoding:'utf8'});
 const report=JSON.parse(result.trim().split('PRE_BATCH:')[1]);
 assert.equal(report.best.parameters.x,2);assert.equal(report.trials[2].status,'failed');assert.equal(report.best.metrics.loss,0);
});
test('SSH guard does not execute the batch on a local terminal',()=>{
 const result=execFileSync('python3',['-c',sshOnly('raise RuntimeError("must not execute locally")')],{env:workerEnvironment(),encoding:'utf8'});
 assert.equal(result.trim(),'__PRE_NO_SSH__');
});
