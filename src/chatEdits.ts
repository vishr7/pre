import type {Cell,ProjectFile} from './api';
export type ChatEdit={target:'cell'|'file';id:string;old_text:string;new_text:string;reason:string;remove?:boolean};
export type EditProposal={edits:ChatEdit[]; originals:Record<string,string>};
export function prepareChatEdits(edits:ChatEdit[],cells:Cell[],files:ProjectFile[]):EditProposal{
 // Expand matching LaTeX counterparts before review, so every change is visible
 // and the existing atomic compile/apply path covers both representations.
 const explicitTargets=new Set(edits.map(e=>e.target+':'+e.id));
 edits = [...edits];
 const targets = [
  ...cells.filter(c=>c.type==='latex').map(c=>({target:'cell' as const,id:c.id,source:c.source})),
  ...files.filter(f=>f.path.endsWith('.tex')).map(f=>({target:'file' as const,id:f.path,source:f.content})),
 ];
 for(const edit of [...edits]){
  const origin=targets.find(t=>t.target===edit.target&&t.id===edit.id);
  if(!origin || edit.remove || !edit.new_text.trim())continue;
  for(const other of targets){
   if(other.target===edit.target || !other.source.trim())continue;
   const linked=origin.source.trim()===other.source.trim() || origin.source.includes(other.source.trim()) || other.source.includes(origin.source.trim());
   if(!linked || !edit.old_text || !other.source.includes(edit.old_text))continue;
   if(explicitTargets.has(other.target+':'+other.id))continue;
   if(edits.some(e=>e.target===other.target&&e.id===other.id&&e.old_text===edit.old_text))continue;
   edits.push({...edit,target:other.target,id:other.id,reason:'Keep matching paper and notebook content consistent: '+edit.reason});
  }
 }
 const originals:Record<string,string>={};
 for(const edit of edits){const source=edit.target==='cell'?cells.find(c=>c.id===edit.id)?.source:files.find(f=>f.path===edit.id)?.content;if(source===undefined)throw new Error('The edit target no longer exists.');originals[edit.target+':'+edit.id]=source;}
 return {edits,originals};
}
export function patchedSources(proposal:EditProposal,cells:Cell[],files:ProjectFile[]){
 const result:Record<string,string>={};
 for(const [key,original] of Object.entries(proposal.originals)){
 const edits=proposal.edits.filter(edit=>edit.target+':'+edit.id===key);const first=edits[0];
 const current=first.target==='cell'?cells.find(c=>c.id===first.id)?.source:files.find(f=>f.path===first.id)?.content;
 if(current!==original)throw new Error('This source changed since the suggestion. Ask AI for a fresh edit.');
 if(edits.some(e=>e.remove) && (edits.length!==1 || edits[0].old_text!==original || edits[0].new_text!==''))throw new Error('Removal must match the complete original source.');
 const ranges=edits.map(edit=>{const start=original.indexOf(edit.old_text);if(!edit.old_text||start<0||original.indexOf(edit.old_text,start+1)>=0)throw new Error('The suggested text is not a unique match.');return {...edit,start,end:start+edit.old_text.length};}).sort((a,b)=>a.start-b.start);
 for(let i=1;i<ranges.length;i++)if(ranges[i].start<ranges[i-1].end)throw new Error('Suggested edits overlap.');
 let source=original;for(const edit of ranges.reverse())source=source.slice(0,edit.start)+edit.new_text+source.slice(edit.end);result[key]=source;
 }
 return result;
}
