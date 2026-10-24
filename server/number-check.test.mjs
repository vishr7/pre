import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { evaluate, matchesClaim, checkCalculations, checkNumbers } from './ai/number-check.mjs';
import { mergeNumberChecks } from './ai/review.mjs';
const paper = readFileSync(new URL('../samples/litetune_paper.tex', import.meta.url), 'utf8');
const calc = (quote, expression, claimed_value, comparison = 'equals') => ({ quote, description: 'test', expression, claimed_value, comparison });
// The six planted arithmetic errors in samples/litetune_paper.tex, plus two correct calculations.
const litetune = [
 calc('a corpus of 12,000 labeled examples', '9000 + 1500 + 2000', '12000'),
 calc('LiteTune (ours) & 84.2 & 79.6 & 88.1 & 85.3', '(84.2 + 79.6 + 88.1) / 3', '85.3'),
 calc('which reduces the error rate by 40\\%', '((100 - 85.0) - (100 - 88.0)) / (100 - 85.0) * 100', '40'),
 calc('trains only 0.5\\% of model parameters', '1.2 / 125 * 100', '0.5'),
 calc('making it 3x faster', '4.5 / 2.0', '3'),
 calc('removing it causes a drop of 2 points', '88.0 - 87.9', '2'),
 calc('Full fine-tuning & 83.1 & 78.9 & 87.0 & 83.0', '(83.1 + 78.9 + 87.0) / 3', '83.0'),
 calc('Adapters & 82.5 & 78.2 & 86.4 & 82.4', '(82.5 + 78.2 + 86.4) / 3', '82.4'),
];
test('Evaluator handles arithmetic and rejects anything else',()=>{
 assert.equal(evaluate('(84.2 + 79.6 + 88.1) / 3').toFixed(2),'83.97');
 assert.equal(evaluate('-2 * (3 + 1)'),-8);
 assert.throws(()=>evaluate('process.exit()'),/Unsupported/);
 assert.throws(()=>evaluate('2 ** 3'),/Could not|Expected/);
 assert.throws(()=>evaluate('(1 + 2'),/Unbalanced/);
});
test('Claims match after rounding to the stated precision',()=>{
 assert.equal(matchesClaim(83.967,'84.0'),true);
 assert.equal(matchesClaim(83.967,'85.3'),false);
 assert.equal(matchesClaim(1.1,'3','at_least'),false);
 assert.equal(matchesClaim(3.4,'3','at_least'),true);
 assert.equal(matchesClaim(12500,'12,000'),false);
});
test('All six planted LiteTune calculation errors are flagged and correct ones are not',()=>{
 const comments=checkCalculations(paper,litetune);
 assert.equal(comments.length,6);
 assert.ok(comments.every(c=>paper.includes(c.quote)&&c.category==='inconsistent_metric'));
 assert.match(comments[1].comment,/= 83\.97/);
 assert.equal(comments[0].section,'Experimental Setup');
 assert.equal(comments[3].section,'Abstract');
});
test('Unanchored quotes and unsafe expressions are dropped',()=>{
 assert.equal(checkCalculations(paper,[calc('not in this paper','1 + 1','3'),calc('making it 3x faster','alert(1)','3')]).length,0);
});
test('Number check runs through Gemini and merges into the review',async()=>{
 const numbers=await checkNumbers(paper,{env:{GEMINI_API_KEY:'k',GEMINI_MODEL:'m'},fetchImpl:async()=>({ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify({calculations:litetune})}]}}]})})});
 const review={summary:'s',scores:{methodology:2,novelty:2,clarity:3,reproducibility:2},action_items:[],
  comments:[{id:'c1',section:'Results',quote:'making it 3x faster',category:'inconsistent_metric',severity:'minor',comment:'Guess.',suggestion:'x'},
   {id:'c2',section:'Introduction',quote:'statistically significantly better',category:'unsupported_claim',severity:'critical',comment:'No test.',suggestion:'y'}]};
 const merged=mergeNumberChecks(review,numbers);
 assert.deepEqual(merged.comments.map(c=>c.id),['c2','m1','m2','m3','m4','m5','m6']);
 assert.deepEqual(merged.action_items.at(-1).related_comment_ids,['m1','m2','m3','m4','m5','m6']);
});
