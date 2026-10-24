import test from 'node:test';
import assert from 'node:assert/strict';
import {prepare,scoreReview} from '../scripts/evaluation/core.mjs';
const record={id:'a',paper_id:'paper',source:'fixture',license:'project-authored',text:'Each model was trained once.',expected_issues:[{quote:'Each model was trained once.',category:'experimental'}]};
test('all reviews and versions of a paper stay in one split',()=>{
 const rows=prepare([record,{...record,id:'b',text:'Another paper version.' ,expected_issues:[]}]);
 assert.equal(rows[0].split,rows[1].split);assert.equal(rows[0].split,prepare([record])[0].split);
});
test('preparation rejects ambiguous duplicate groups and unanchored reference issues',()=>{
 assert.throws(()=>prepare([record,{...record,id:'b',paper_id:'different'}]),/Duplicate paper text/);
 assert.throws(()=>prepare([{...record,expected_issues:[{quote:'Invented quote',category:'clarity'}]}]),/Unanchored/);
 assert.throws(()=>prepare([{...record,license:''}]),/license/);
});
test('evaluation separates grounding from scientific quality and leaves empty precision undefined',()=>{
 const review={summary:'Review',scores:{methodology:2,novelty:3,clarity:4,reproducibility:1},comments:[{id:'c1',quote:record.text,category:'experimental',severity:'major',comment:'Repeat runs.',suggestion:'Report variability.'},{id:'c2',quote:'Invented evidence',severity:'minor',comment:'Bad',suggestion:'Bad'}],action_items:[{related_comment_ids:['missing']}]};
 const scores=scoreReview(record,review);assert.equal(scores.quote_accuracy,0.5);assert.equal(scores.reference_overlap_recall,1);assert.equal(scores.broken_action_links,1);assert.equal(scores.needs_human_review,true);
 assert.equal(scoreReview(record,{...review,comments:[]}).quote_accuracy,null);
});
