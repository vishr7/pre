import { test } from 'node:test';
import assert from 'node:assert/strict';
import { findPaper, paperSections, validateReview, reviewPaper } from './ai/review.mjs';
const latex = '\\begin{abstract}\nWe reach 94.2\\% accuracy.\n\\end{abstract}\n\\section{Experiments}\nEach model was trained once.';
const comment = (id, quote) => ({ id, section: 'Experiments', quote, category: 'experimental', severity: 'major', comment: 'Single run.', suggestion: 'Use 5 seeds.' });
const gemini = body => ({ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify(body)}]}}]})});
const isNumberCheck = options => JSON.parse(options.body).contents[0].parts[0].text.startsWith('You audit the arithmetic');
const review = comments => ({ summary: 'Summary.', scores: { methodology: 2, novelty: 3, clarity: 4, reproducibility: 1 }, comments,
  action_items: [{ id: 'a1', title: 'Run seeds', description: 'Add seeds.', related_comment_ids: comments.map(c => c.id) }] });
test('Review finds paper/main.tex first, then LaTeX cells',()=>{
 assert.equal(findPaper({files:[{path:'notes.tex',content:'x'},{path:'paper/main.tex',content:latex}]}),latex);
 assert.equal(findPaper({files:[],cells:[{type:'python',source:'1'},{type:'latex',source:'A'},{type:'latex',source:'B'}]}),'A\n\nB');
 assert.deepEqual(paperSections(latex),['Abstract','Experiments']);
});
test('Review keeps verbatim quotes and drops invented ones',()=>{
 const result=validateReview(latex,review([comment('c1','Each model was trained once.'),comment('c2','We reach 94.2% accuracy.')]));
 assert.deepEqual(result.comments.map(c=>c.id),['c1']);
 assert.deepEqual(result.action_items[0].related_comment_ids,['c1']);
});
test('Review retries when no quote is anchored, without exposing credentials',async()=>{
 let calls=0;
 const result=await reviewPaper({files:[{path:'paper/main.tex',content:latex}],venue:'neurips'},{env:{GEMINI_API_KEY:'test-secret',GEMINI_MODEL:'test-model'},fetchImpl:async(url,options)=>{
   assert.equal(options.headers['x-goog-api-key'],'test-secret');assert.ok(!url.includes('test-secret'));
   if(isNumberCheck(options))return gemini({calculations:[]});
   calls++;const body=calls===1?review([comment('c1','not in the paper')]):review([comment('c1','Each model was trained once.')]);
   return {ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify(body)}]}}]})};
 }});
 assert.equal(calls,2);assert.equal(result.comments[0].quote,'Each model was trained once.');
});
test('Review without a paper is explicit',async()=>{
 await assert.rejects(reviewPaper({files:[],cells:[]},{env:{GEMINI_API_KEY:'k',GEMINI_MODEL:'m'}}),/No paper found/);
});
test('Review uses assembled source including notebook text rather than the starter file',async()=>{
 const result=await reviewPaper({latex,files:[{path:'paper/main.tex',content:'Empty starter'}]}, {env:{GEMINI_API_KEY:'test',GEMINI_MODEL:'test'},fetchImpl:async(_url,options)=>{
 if(isNumberCheck(options))return gemini({calculations:[]});
 assert.ok(JSON.parse(options.body).contents[0].parts[0].text.includes('Each model was trained once.'));
 return {ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify(review([comment('c1','Each model was trained once.')]))}]}}]})};
 }});
 assert.equal(result.comments.length,1);
});
