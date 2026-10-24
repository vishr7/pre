import test from 'node:test';
import assert from 'node:assert/strict';
import { structured_call } from './ai/structured-call.mjs';
const env={GEMINI_API_KEY:'test',GEMINI_MODEL:'test'};
const args={prompt:'test',schema:{},validate:value=>value};
const success={ok:true,json:async()=>({candidates:[{content:{parts:[{text:'{"ok":true}'}]}}]})};
test('retries a temporary 503 and returns a successful response',async()=>{
 let calls=0;const delays=[];
 const result=await structured_call(args,{env,sleep:async ms=>delays.push(ms),fetchImpl:async()=>++calls<3?{ok:false,status:503}:success});
 assert.equal(result.ok,true);assert.equal(calls,3);assert.deepEqual(delays,[1000,2000]);
});
test('persistent outage stops after three attempts with an actionable message',async()=>{
 let calls=0;
 await assert.rejects(structured_call(args,{env,sleep:async()=>{},fetchImpl:async()=>{calls++;return {ok:false,status:503};}}),/temporarily unavailable.*3 attempts/);
 assert.equal(calls,3);
});
test('does not retry authorization failures',async()=>{
 let calls=0;
 await assert.rejects(structured_call(args,{env,fetchImpl:async()=>{calls++;return {ok:false,status:403};}}),/rejected API access/);
 assert.equal(calls,1);
});
test('retries connection failures and caps Retry-After delays',async()=>{
 let calls=0;const delays=[];
 await structured_call(args,{env,sleep:async ms=>delays.push(ms),fetchImpl:async()=>{
 calls++;if(calls===1)throw new TypeError('fetch failed');
 if(calls===2)return {ok:false,status:429,headers:{get:()=> '120'}};
 return success;
 }});
 assert.deepEqual(delays,[1000,5000]);
});
