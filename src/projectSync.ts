import type {Cell,ProjectFile} from './api';
export type Workspace={cells:Cell[];files:ProjectFile[]};
// File-backed cells are views of the file, identified by path rather than text.
export function linkFiles(cells:Cell[],files:ProjectFile[]):Workspace{
 const next=cells.filter(c=>!c.filePath||files.some(f=>f.path===c.filePath)).map(c=>({...c}));
 for(const file of files.filter(f=>f.path.endsWith('.tex'))){
  let cell=next.find(c=>c.filePath===file.path);
  if(!cell)cell=next.find(c=>!c.filePath&&c.type==='latex'&&c.source.trim()===file.content.trim());
  if(cell){if(cell.source!==file.content){cell.output=undefined;cell.error=undefined;cell.images=[];cell.status=undefined;}cell.filePath=file.path;cell.type='latex';cell.source=file.content;}
  else next.push({id:'file:'+file.path,filePath:file.path,type:'latex',source:file.content});
 }
 return {cells:next,files};
}
export function changeCells(state:Workspace,cells:Cell[]):Workspace{
 const removed=new Set(state.cells.filter(c=>c.filePath&&!cells.some(n=>n.id===c.id)).map(c=>c.filePath));
 const files=state.files.filter(f=>!removed.has(f.path)).map(f=>{
  const cell=cells.find(c=>c.filePath===f.path&&c.type==='latex');return cell?{...f,content:cell.source}:f;
 });
 return linkFiles(cells.map(c=>c.filePath&&c.type!=='latex'?{...c,filePath:undefined}:c),files);
}

// Preserve the existing cell structure when a Paper edit maps to one source.
// Cross-source edits consolidate the rendered source, retaining a recovery copy.
export function editPaper(state:Workspace, before:string, after:string, assemble:(files:ProjectFile[],cells:Cell[])=>string):Workspace{
 if(before===after)return state;
 let start=0;while(start<before.length&&start<after.length&&before[start]===after[start])start++;
 let end=before.length,newEnd=after.length;
 while(end>start&&newEnd>start&&before[end-1]===after[newEnd-1]){end--;newEnd--;}
 const old=before.slice(start,end),replacement=after.slice(start,newEnd);
 const candidates=[...state.files.filter(f=>f.path.endsWith('.tex')).map(f=>({kind:'file',id:f.path,source:f.content})),...state.cells.filter(c=>c.type==='latex'&&!c.filePath).map(c=>({kind:'cell',id:c.id,source:c.source}))];
 for(const target of candidates){
  // Include adjacent context to disambiguate insertions and repeated words.
  const left=before.slice(Math.max(0,start-60),start),right=before.slice(end,end+60);
  const needle=left+old+right;
  const positions:number[]=[];
  if(needle){let at=target.source.indexOf(needle);while(at>=0){positions.push(at+left.length);at=target.source.indexOf(needle,at+1);}}
  if(old){let at=target.source.indexOf(old);while(at>=0&&positions.length<200){positions.push(at);at=target.source.indexOf(old,at+1);}}
  else if(target.source===before)positions.push(start);
  for(const at of new Set(positions)){
   const source=target.source.slice(0,at)+replacement+target.source.slice(at+old.length);
   const next=target.kind==='file'?linkFiles(state.cells,state.files.map(f=>f.path===target.id?{...f,content:source}:f)):changeCells(state,state.cells.map(c=>c.id===target.id?{...c,source}:c));
   try{if(assemble(next.files,next.cells)===after)return next;}catch{ /* Try another mapping. */ }
  }
 }
 const backup={cells:state.cells.filter(c=>c.type==='latex'),files:state.files.filter(f=>f.path.endsWith('.tex'))};
 const files=[...state.files.filter(f=>!f.path.endsWith('.tex')),{path:`history/paper-before-edit-${crypto.randomUUID()}.json`,content:JSON.stringify(backup,null,2)},{path:'paper/main.tex',content:after}];
 const first=state.cells.findIndex(c=>c.type==='latex');
 const cells=state.cells.filter(c=>c.type!=='latex');
 cells.splice(first<0?cells.length:Math.min(first,cells.length),0,{id:'file:paper/main.tex',filePath:'paper/main.tex',type:'latex',source:after});
 return linkFiles(cells,files);
}
