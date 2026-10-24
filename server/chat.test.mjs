import test from 'node:test';
import assert from 'node:assert/strict';
import {chatReply} from './ai/chat.mjs';
const dependencies=value=>({env:{GEMINI_API_KEY:'test',GEMINI_MODEL:'test'},fetchImpl:async()=>({ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify(value)}]}}]})})});
test('chat returns code for insertion, without executing it',async()=>{
 const expected={message:'Here is a plot.',cells:[{language:'python',source:'print(42)'}]};
 assert.deepEqual(await chatReply({messages:[{role:'user',text:'Write code'}]},dependencies(expected)),expected);
});
test('chat accepts plain explanations and rejects unsupported code cells',async()=>{
 assert.deepEqual(await chatReply({messages:[{role:'user',text:'Explain'}]},dependencies({message:'An explanation',cells:[]})),{message:'An explanation',cells:[]});
 await assert.rejects(chatReply({messages:[{role:'user',text:'Code'}]},dependencies({message:'Code',cells:[{language:'shell',source:'echo hi'}]})),/Invalid generated cell/);
});
test('chat sends result plots as image parts, not embedded text',async()=>{
 await chatReply({messages:[{role:'user',text:'Compare my results'}],context:{replication:{latestRun:{stdout:'loss: 0.01',codeChangedSinceRun:true}},figures:[{label:'Run figure',mimeType:'image/png',data:'aGVsbG8='}]}},{env:{GEMINI_API_KEY:'test',GEMINI_MODEL:'test'},fetchImpl:async(_url,options)=>{
 const parts=JSON.parse(options.body).contents[0].parts;
 assert.ok(parts[0].text.includes('loss: 0.01'));assert.ok(parts[0].text.includes('older code version'));
 assert.ok(!parts[0].text.includes('aGVsbG8='));assert.equal(parts[1].inlineData.mimeType,'image/png');
 return {ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify({message:'Analysis',cells:[]})}]}}]})};
 }});
});
