import test from 'node:test';
import { existsSync } from 'node:fs';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { replicate } from './replicate.mjs';
const cwd=fileURLToPath(new URL('../',import.meta.url));
const options={cwd,python:process.env.PRE_PYTHON||`${cwd}.venv/bin/python`};
const scienceAvailable=!!process.env.PRE_PYTHON||existsSync(options.python);
test('Replicate bridge compares real metrics with explicit tolerances',{skip:!scienceAvailable},async()=>{
 const result=await replicate({action:'compare',published_metrics:[{name:'accuracy',value:0.9,absolute_tolerance:0.01,relative_tolerance:0}],reproduced_metrics:{accuracy:0.905}},options);
 assert.equal(result.comparisons[0].status,'match');assert.equal(result.source_kind,'user_measurements');
});
test('Replicate rejects negative tolerances and unsupported actions',{skip:!scienceAvailable},async()=>{
 await assert.rejects(replicate({action:'compare',published_metrics:[{name:'score',value:1,absolute_tolerance:-1,relative_tolerance:0}],reproduced_metrics:{score:1}},options));
 assert.throws(()=>replicate({action:'execute',code:'print(1)'},options),/Choose/);
});
test('fixed local example executes and reports actual metric agreement',{skip:!scienceAvailable},async()=>{
 const result=await replicate({action:'demo',code:'raise Exception("Must never execute user code")'},options);
 assert.equal(result.scientific.execution_status,'success');
 assert.equal(result.scientific.reproduced_metrics.mean,30);
 assert.equal(result.scientific.all_published_metrics_agree,true);
 assert.equal(result.source_kind,'local_baseline');
});
test('syntax checks do not execute Python', {skip:!scienceAvailable}, async()=>{
 assert.equal((await replicate({action:'syntax',code:'raise RuntimeError("not executed")'},options)).valid,true);
 const invalid=await replicate({action:'syntax',code:'def broken('},options);
 assert.equal(invalid.valid,false);assert.match(invalid.error,/Line 1/);
});
