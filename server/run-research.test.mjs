import test from 'node:test';
import assert from 'node:assert/strict';
import {runResearch} from '../src/runResearch.ts';
const plan={code:'def run_trial(p): return {"loss":1}',configurations:'[{}]',metric:'loss',direction:'minimize',parallel:1,execution:'ssh',summary:'Test',writeAnalysis:true};
test('explicit SSH plans never fall back locally',async()=>{
 let requests=0;
 await assert.rejects(runResearch(plan,null,async()=>{requests++;},()=>{}),/SSH is required/);
 assert.equal(requests,0);
});
test('terminal failure does not trigger a local duplicate run',async()=>{
 let requests=0;
 await assert.rejects(runResearch(plan,{activeTitle:()=> 'SSH',run:async()=>({exitCode:1,output:'missing module'})},async()=>{requests++;},()=>{}),/No local retry/);
 assert.equal(requests,0);
});
test('local completion returns measurements for analysis',async()=>{
 const result=await runResearch({...plan,execution:'auto'},null,async path=>path.endsWith('start')?{id:'1',status:'running',trials:[]}:{id:'1',status:'completed',trials:[{status:'success',metrics:{loss:1}}]},()=>{},async()=>{});
 assert.equal(result.ranOn,'Local');assert.equal(result.trials[0].metrics.loss,1);
});
