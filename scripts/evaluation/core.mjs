import {createHash} from 'node:crypto';
export const digest=value=>createHash('sha256').update(value).digest('hex');
export function prepare(records){
 const seen=new Set();const groups=new Map();const output=[];
 for(let row of records){
  for(const key of ['id','paper_id','source','license','text'])if(typeof row[key]!=='string'||!row[key].trim())throw new Error(`Each record needs ${key}.`);
  if(seen.has(row.id))throw new Error(`Duplicate record ID: ${row.id}`);seen.add(row.id);
  if(row.text.length>200000)throw new Error(`Paper ${row.id} exceeds the reviewer limit.`);
  const textHash=digest(row.text.replace(/\s+/g,' ').trim());
  const group=row.group_id||`${row.source}:${row.paper_id}`;
  // Exact duplicate paper text must not appear under different split groups.
  if(groups.has(textHash)&&groups.get(textHash)!==group)throw new Error('Duplicate paper text has different group IDs; assign one shared group_id.');
  groups.set(textHash,group);
  const bucket=parseInt(digest(group).slice(0,8),16)%100;
  row={...row,group_id:group,text_sha256:textHash,split:bucket<80?'train':bucket<90?'validation':'test'};
  if(row.expected_issues!==undefined&&!Array.isArray(row.expected_issues))throw new Error('expected_issues must be an array.');
  for(const issue of row.expected_issues||[])if(typeof issue.quote!=='string'||!issue.quote.trim()||!row.text.includes(issue.quote)||typeof issue.category!=='string')throw new Error(`Unanchored reference issue in ${row.id}.`);
  output.push(row);
 }
 return output;
}
export function scoreReview(record,review){
 const comments=Array.isArray(review?.comments)?review.comments:[];
 const valid=typeof review?.summary==='string'&&Array.isArray(review?.comments)&&Array.isArray(review?.action_items)&&['methodology','novelty','clarity','reproducibility'].every(k=>Number.isInteger(review?.scores?.[k])&&review.scores[k]>=1&&review.scores[k]<=5)&&comments.every(c=>typeof c.id==='string'&&typeof c.quote==='string'&&typeof c.comment==='string'&&typeof c.suggestion==='string'&&['minor','major','critical'].includes(c.severity));
 const anchored=comments.filter(c=>typeof c.quote==='string'&&c.quote.trim().length>=4&&record.text.includes(c.quote));
 const references=record.expected_issues||[];
 const matched=references.filter(issue=>anchored.some(c=>c.category===issue.category&&(c.quote.includes(issue.quote)||issue.quote.includes(c.quote))));
 const ids=new Set(comments.map(c=>c.id));
 return {schema_valid:valid,comments:comments.length,anchored_comments:anchored.length,quote_accuracy:comments.length?anchored.length/comments.length:null,broken_action_links:(review?.action_items||[]).flatMap(a=>a.related_comment_ids||[]).filter(id=>!ids.has(id)).length,reference_issues:references.length,reference_overlap_recall:references.length?matched.length/references.length:null,reference_human_validated:record.human_validated===true,needs_human_review:true};
}
