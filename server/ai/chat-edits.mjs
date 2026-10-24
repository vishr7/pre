export function validateChatEdits(edits, context) {
 if(!Array.isArray(edits)||edits.length>20)throw new Error('Expected at most 20 targeted edits.');
 const groups=new Map();
 for(const edit of edits){
  if(!['cell','file'].includes(edit?.target)||typeof edit.id!=='string'||typeof edit.old_text!=='string'||!edit.old_text||typeof edit.new_text!=='string'||edit.new_text.length>100000||typeof edit.reason!=='string')throw new Error('Invalid targeted edit.');
  const source=edit.target==='cell'?context.notebook?.find(c=>c.id===edit.id)?.source:context.files?.find(f=>f.path===edit.id)?.content;
  if(typeof source!=='string'||source.includes('[Truncated for chat]'))throw new Error('Target source is unavailable or truncated. Ask for a smaller target.');
  const start=source.indexOf(edit.old_text);
  if(start<0||source.indexOf(edit.old_text,start+1)>=0||edit.old_text===edit.new_text)throw new Error('Each edit must match a unique original quote and change it.');
  const key=edit.target+':'+edit.id;const ranges=groups.get(key)||[];
  if(ranges.some(r=>start<r.end&&start+edit.old_text.length>r.start))throw new Error('Edits cannot overlap.');
  ranges.push({start,end:start+edit.old_text.length});groups.set(key,ranges);
 }
 return edits;
}
