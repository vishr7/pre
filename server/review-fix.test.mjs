import { test } from 'node:test';
import assert from 'node:assert/strict';
import { proposeReviewFix, excerptAround } from './ai/review-fix.mjs';
const source = '\\section{Results}\nTraining took 2.0 hours versus 4.5 hours, making it 3x faster.\n';
const comment = { id: 'm1', quote: 'making it 3x faster', comment: 'The paper states 3, but 4.5 / 2.0 = 2.25.', suggestion: 'Correct to 2.25.', category: 'inconsistent_metric' };
const target = { target: 'file', id: 'paper/main.tex', source };
const gemini = replies => { let calls = 0; return { calls: () => calls, env: { GEMINI_API_KEY: 'k', GEMINI_MODEL: 'm' },
  fetchImpl: async () => ({ ok: true, json: async () => ({ candidates: [{ content: { parts: [{ text: JSON.stringify(replies[Math.min(calls++, replies.length - 1)]) }] } }] }) }) }; };
test('Fix returns a targeted chat-style edit for the quoted file',async()=>{
 const result=await proposeReviewFix({comment,target},gemini([{message:'Corrected the speedup.',edits:[{old_text:'3x faster',new_text:'2.25x faster',reason:'4.5 / 2.0 = 2.25'}]}]));
 assert.deepEqual(result.edits,[{target:'file',id:'paper/main.tex',old_text:'3x faster',new_text:'2.25x faster',reason:'4.5 / 2.0 = 2.25'}]);
});
test('Fix retries edits whose text is not in the source',async()=>{
 const deps=gemini([{message:'x',edits:[{old_text:'not in the paper',new_text:'y',reason:'r'}]},{message:'ok',edits:[{old_text:'3x',new_text:'2.25x',reason:'r'}]}]);
 const result=await proposeReviewFix({comment,target},deps);
 assert.equal(deps.calls(),2);assert.equal(result.edits[0].new_text,'2.25x');
});
test('Fix may decline when new experiments are needed',async()=>{
 const result=await proposeReviewFix({comment,target},gemini([{message:'Run 5 seeds and report variance.',edits:[]}]));
 assert.equal(result.edits.length,0);assert.match(result.message,/seeds/);
});
test('Fix rejects a stale quote or missing target before calling Gemini',async()=>{
 await assert.rejects(proposeReviewFix({comment:{...comment,quote:'gone'},target},gemini([])),/no longer/);
 await assert.rejects(proposeReviewFix({comment,target:{target:'file',id:'x'}},gemini([])),/cell or file/);
});
test('Fix sends only the text around the quote, with low thinking',async()=>{
 const long='\\section{Intro}\n'+'Filler sentence about prior work.\n'.repeat(300)+source+'Closing remarks.\n'.repeat(300);
 let body;
 await proposeReviewFix({comment,target:{...target,source:long}},{env:{GEMINI_API_KEY:'k',GEMINI_MODEL:'m'},fetchImpl:async(_url,options)=>{
  body=JSON.parse(options.body);
  return {ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify({message:'ok',edits:[{old_text:'3x faster',new_text:'2.25x faster',reason:'r'}]})}]}}]})};
 }});
 assert.deepEqual(body.generationConfig.thinkingConfig,{thinkingLevel:'low'});
 const prompt=body.contents[0].parts[0].text;
 assert.ok(prompt.includes('making it 3x faster'));assert.ok(prompt.length<long.length/2);
});
test('Excerpt keeps whole lines around the quote',()=>{
 assert.equal(excerptAround('a\nb quote c\nd','quote',0),'b quote c');
});
