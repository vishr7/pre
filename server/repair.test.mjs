import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateRepair, proposeLatexRepair } from './ai/repair.mjs';
const source = '\\documentclass{article}\n\\begin{document}\nHello';
const proposal = {summary:'Close the document.',edits:[{old_text:'Hello',new_text:'Hello\n\\end{document}',reason:'The document was not closed.'}]};
test('Repair adds a targeted closing command without changing the original',()=>{
 const result=validateRepair(source,proposal);
 assert.equal(result.source,source+'\n\\end{document}');assert.equal(source.endsWith('Hello'),true);
});
test('Repair rejects missing, ambiguous, overlapping, and unsafe replacements',()=>{
 assert.throws(()=>validateRepair(source,{...proposal,edits:[{...proposal.edits[0],old_text:'Not here'}]}),/exactly once/);
 assert.throws(()=>validateRepair('Hello Hello',proposal),/exactly once/);
 assert.throws(()=>validateRepair(source,{...proposal,edits:[proposal.edits[0],proposal.edits[0]]}),/overlap/);
 assert.throws(()=>validateRepair(source,{...proposal,edits:[{...proposal.edits[0],new_text:'\\write18{bad}'}]}),/unsafe/);
});
test('Repair applies multiple exact edits against original offsets',()=>{
 const result=validateRepair('alpha beta gamma',{summary:'Two edits',edits:[{old_text:'gamma',new_text:'g',reason:'Shorten'},{old_text:'alpha',new_text:'first',reason:'Rename'}]});
 assert.equal(result.source,'first beta g');
});
test('AI validation retries invalid proposals without exposing credentials',async()=>{
 let calls=0;
 const result=await proposeLatexRepair({source,error:'no legal end found'},{env:{GEMINI_API_KEY:'test-secret',GEMINI_MODEL:'test-model'},fetchImpl:async(url,options)=>{
   assert.equal(options.headers['x-goog-api-key'],'test-secret');assert.ok(!url.includes('test-secret'));
   calls++;return {ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify(calls===1?{...proposal,edits:[{...proposal.edits[0],old_text:'missing'}]}:proposal)}]}}]})};
 }});
 assert.equal(calls,2);assert.match(result.source,/end\{document\}/);
});
test('Missing AI configuration and empty suggestions are explicit',async()=>{
 await assert.rejects(proposeLatexRepair({source,error:'error'},{env:{}}),/GEMINI_API_KEY/);
 const result=validateRepair(source,{summary:'The missing asset must be uploaded.',edits:[]});
 assert.equal(result.source,source);assert.equal(result.edits.length,0);
});
