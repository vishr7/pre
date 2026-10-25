import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { evaluate, matchesClaim, checkCalculations, checkNumbers, arithmeticScore, auditCalculations, correctedValue } from './ai/number-check.mjs';
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
 assert.equal(merged.scores.arithmetic,2); // 2 of 8 calculations correct
 assert.equal(merged.scores.methodology,2);
});
test('Arithmetic score reflects the share of correct calculations',()=>{
 assert.equal(arithmeticScore({checked:8,comments:[]}),5);
 assert.equal(arithmeticScore({checked:8,comments:Array(8)}),1);
 assert.equal(arithmeticScore({checked:4,comments:Array(2)}),3);
 assert.equal(arithmeticScore({checked:0,comments:[]}),null);
 const review={summary:'s',scores:{methodology:3,novelty:3,clarity:3,reproducibility:3},comments:[],action_items:[]};
 assert.equal(mergeNumberChecks(review,null).scores.arithmetic,null); // audit failed
 assert.equal(mergeNumberChecks(review,{checked:3,comments:[]}).scores.arithmetic,5);
});
// A different, made-up clinical paper so the clean-up rules are not tuned to LiteTune.
const clinical = `\\begin{abstract}
We enrolled 240 patients and the response rate improved from 40\\% to 50\\%, a 50\\% relative improvement.
\\end{abstract}
\\section{Methods}
Patients were split into 120 treatment and 100 control participants.
\\section{Results}
Response improved from 40\\% to 50\\%, which is a 50\\% relative improvement and proves the drug works for every disease.
Mean recovery time fell to 12.4 days.
`;
const relative = (quote) => calc(quote, '(50 - 40) / 40 * 100', '50');
test('Same calculation stated twice gets one comment per place, each pointing to the other',()=>{
 const {comments}=auditCalculations(clinical,[relative('a 50\\% relative improvement'),relative('which is a 50\\% relative improvement'),relative('which is a 50\\% relative improvement')]);
 assert.equal(comments.length,2); // the repeated item at the same spot is reported once
 assert.match(comments[0].comment,/also stated in Results/);assert.match(comments[1].comment,/also stated in Abstract/);
});
test('Corrected values follow the precision the paper uses',()=>{
 assert.equal(correctedValue(83.9667,'85.3'),'84.0 (exactly 83.97)');
 assert.equal(correctedValue(2.25,'3'),'2.25');
 assert.equal(correctedValue(12500,'12,000'),'12,500');
 assert.equal(correctedValue(12.4,'12.0'),'12.4');
 assert.match(auditCalculations(clinical,[calc('We enrolled 240 patients','120 + 100','240')]).comments[0].suggestion,/to 220,/);
});
test('Reviewer number comments on checked passages are dropped, other categories are kept',()=>{
 const audit=auditCalculations(clinical,[relative('which is a 50\\% relative improvement')]);
 const reviewer={summary:'s',scores:{methodology:3,novelty:3,clarity:3,reproducibility:3},comments:[
  {id:'c1',section:'Results',quote:'Response improved from 40\\% to 50\\%, which is a 50\\% relative improvement',category:'inconsistent_metric',severity:'critical',comment:'Should be 25%.',suggestion:'x'},
  {id:'c2',section:'Results',quote:'proves the drug works for every disease',category:'unsupported_claim',severity:'critical',comment:'Overclaim.',suggestion:'y'},
  {id:'c3',section:'Results',quote:'Mean recovery time fell to 12.4 days.',category:'inconsistent_metric',severity:'minor',comment:'No baseline given.',suggestion:'z'}],
  action_items:[{id:'a1',title:'Fix the relative improvement',description:'d',related_comment_ids:['c1']},{id:'a2',title:'Tone down claims',description:'d',related_comment_ids:['c2']},{id:'a3',title:'General polish',description:'d',related_comment_ids:[]}]};
 const merged=mergeNumberChecks(reviewer,audit,clinical);
 assert.deepEqual(merged.comments.map(c=>c.id),['c2','m1','c3']); // c1 duplicated the verified check; c3 is about another sentence
 assert.deepEqual(merged.action_items.map(a=>a.id),['a2','a3','a4']); // a1 lost its only comment; new id does not collide
});
