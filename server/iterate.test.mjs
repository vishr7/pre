import test from 'node:test';
import assert from 'node:assert/strict';
import {SweepJobs,validateSweep} from './iterate.mjs';
const spec={code:'def run_trial(p): return {"loss": p["x"]}',configurations:[{x:3},{x:1},{x:2}],metric:'loss',direction:'minimize',parallel:2,approved:true};
test('batch enforces bounds and explicit run',()=>{assert.throws(()=>validateSweep({...spec,parallel:5}));assert.throws(()=>new SweepJobs({}).start({...spec,approved:false}));});
test('runs concurrently within bound, ranks actual metrics, releases every worker',async()=>{
 let active=0,peak=0,released=0;
 const jobs=new SweepJobs({execute:async()=>{const value=++active;peak=Math.max(peak,active);await new Promise(r=>setTimeout(r,15));active--;return {stdout:'PRE_METRICS:'+JSON.stringify({loss:value})};},release:async()=>{released++;}});
 const job=jobs.start(spec);await jobs.jobs.get(job.id).done;
 const result=jobs.get(job.id);assert.equal(peak,2);assert.equal(released,3);assert.equal(result.status,'completed');assert.equal(result.best.metrics.loss,1);assert.equal(result.trials.length,3);
});
test('failed metrics are not ranked as successful measurements',async()=>{
 const jobs=new SweepJobs({execute:async()=>({stdout:'no metric'}),release:async()=>{}});const job=jobs.start(spec);await jobs.jobs.get(job.id).done;assert.equal(jobs.get(job.id).best,null);assert.ok(jobs.get(job.id).trials.every(t=>t.status==='failed'));
});
test('cancel stops active work and leaves queued trials unexecuted',async()=>{
 const pending=new Map();let starts=0;
 const jobs=new SweepJobs({execute:({sessionId})=>{starts++;return new Promise((resolve,reject)=>pending.set(sessionId,reject));},reset:async({sessionId})=>pending.get(sessionId)?.(new Error('stopped')),release:async()=>{}});
 const job=jobs.start(spec);const result=await jobs.cancel(job.id);assert.equal(starts,2);assert.equal(result.status,'cancelled');assert.ok(result.trials.every(t=>t.status==='cancelled'));
});
