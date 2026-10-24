import test from 'node:test';
import assert from 'node:assert/strict';
import {assistantContext} from '../src/assistantContext.ts';
const inputs={cells:[],files:[],review:null,logs:'',compileError:'',selected:null,toolResult:''};
test('connects latest replication measurements with source and stale-code status',()=>{
 const context=assistantContext({...inputs,review:{summary:'Check baselines'},files:[
 {path:'replication/latest-plan.json',content:JSON.stringify({path:'replication/test.py',source:'paper.pdf',plan:{expected_results:'Loss decreases'}})},
 {path:'replication/test.py',content:'print(2)'},
 {path:'replication/test.results.json',content:JSON.stringify({code:'print(1)',stdout:'1',images:['data:image/png;base64,aGVsbG8=']})},
 {path:'.env',content:'secret'},
 ]});
 assert.equal(context.replication.latestRun.stdout,'1');assert.equal(context.replication.latestRun.codeChangedSinceRun,true);
 assert.equal(context.review.summary,'Check baselines');assert.equal(context.figures.length,1);
 assert.ok(!JSON.stringify(context).includes('secret'));
 assert.ok(!JSON.stringify(context.replication).includes('base64'));
});
test('bounds text and images while retaining notebook execution provenance',()=>{
 const context=assistantContext({...inputs,cells:[{id:'a',type:'python',source:'print(2)',executedSource:'print(1)',output:'1',images:['data:image/png;base64,'+'a'.repeat(1100000)]}],files:Array.from({length:40},(_,i)=>({path:`file${i}.py`,content:'x'.repeat(100000)}))});
 assert.equal(context.notebook[0].outputMatchesCurrentSource,false);
 assert.equal(context.figures.length,0);assert.ok(JSON.stringify(context).length<250000);
});
