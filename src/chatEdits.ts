import type {Cell,ProjectFile} from './api';
export type ChatEdit={target:'cell'|'file';id:string;old_text:string;new_text:string;reason:string};
export type EditProposal={edits:ChatEdit[]; originals:Record<string,string>};
export function prepareChatEdits(edits:ChatEdit[],cells:Cell[],files:ProjectFile[]):EditProposal{
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
 const ranges=edits.map(edit=>{const start=original.indexOf(edit.old_text);if(!edit.old_text||start<0||original.indexOf(edit.old_text,start+1)>=0)throw new Error('The suggested text is not a unique match.');return {...edit,start,end:start+edit.old_text.length};}).sort((a,b)=>a.start-b.start);
 for(let i=1;i<ranges.length;i++)if(ranges[i].start<ranges[i-1].end)throw new Error('Suggested edits overlap.');
 let source=original;for(const edit of ranges.reverse())source=source.slice(0,edit.start)+edit.new_text+source.slice(edit.end);result[key]=source;
 }
 return result;
}
