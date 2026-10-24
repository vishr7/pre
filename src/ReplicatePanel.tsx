import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Code2, Copy, FileText, LoaderCircle, LockKeyhole, Plus, Upload, X } from 'lucide-react';
import Editor from '@monaco-editor/react';
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { request, type ProjectFile } from './api';
import { isScientificResult, object, pdfUploadError, safeFigureUrl } from './scientific';
import ScientificResults from './ScientificResults';
GlobalWorkerOptions.workerSrc = workerUrl;

type Plan = {title:string;summary:string;experiment:string;methodology:string;steps:string[];requirements:string[];missing:string[];limitations:string[];code:string;expected_results:string};
type Saved = {plan:Plan;path:string;source:string;paperText?:string};
const manifest = 'replication/latest-plan.json';
function isPlan(value:unknown): value is Plan {
 return object(value) && ['title','summary','experiment','methodology','code','expected_results'].every(key=>typeof value[key]==='string') &&
  ['steps','requirements','missing','limitations'].every(key=>Array.isArray(value[key])&&(value[key] as unknown[]).every(item=>typeof item==='string'));
}
function restore(files:ProjectFile[]):Saved|null {
 try {const value=JSON.parse(files.find(file=>file.path===manifest)?.content||'null');return object(value)&&isPlan(value.plan)&&typeof value.path==='string'&&typeof value.source==='string'?value as Saved:null;} catch {return null;}
}
async function extractPdf(data:Uint8Array, onProgress:(page:number,total:number)=>void) {
 const task=getDocument({data});
 try {
  const pdf=await task.promise;
  if(pdf.numPages>150)throw new Error('Use a paper with at most 150 pages.');
  let text='';
  for(let index=1;index<=pdf.numPages;index++) {
   const page=await pdf.getPage(index);const content=await page.getTextContent();
   text+=`\n[Page ${index}]\n`+content.items.map(item=>'str'in item?item.str+('hasEOL'in item&&item.hasEOL?'\n':' '):'').join('');
   if(text.length>180000)throw new Error('This paper is too long. Upload the relevant pages as a shorter PDF.');
   onProgress(index,pdf.numPages);
  }
  if(text.replace(/\[Page \d+\]/g,'').trim().length<100)throw new Error('This PDF has little readable text. Upload a searchable PDF rather than a scan.');
  return text;
 } finally {await task.destroy();}
}
export default function ReplicatePanel({base,files,onSaveFiles,onInsert,onAnalyze}:{base:string;files:ProjectFile[];onSaveFiles:(files:ProjectFile[])=>void;onInsert:(source:string)=>void;onAnalyze:()=>void}) {
 const [saved,setSaved]=useState<Saved|null>(()=>restore(files));
 const [link,setLink]=useState('');const [pdf,setPdf]=useState<File|null>(null);const [focus,setFocus]=useState('');
 const [busy,setBusy]=useState('');const [error,setError]=useState('');const [syntax,setSyntax]=useState('');
 const [syntaxValid,setSyntaxValid]=useState<boolean|null>(null);const [dragging,setDragging]=useState(false);
 const [progress,setProgress]=useState<{page:number;total:number}|null>(null);const [notice,setNotice]=useState('');
 const upload=useRef<HTMLInputElement>(null);const lock=useRef(false);const alive=useRef(true);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 const code=saved?(files.find(file=>file.path===saved.path)?.content??saved.plan.code):'';
 const output=useMemo(()=>{
  try {const value=JSON.parse(files.find(file=>file.path===saved?.path.replace(/\.py$/,'.results.json'))?.content||'null');return object(value)&&(isScientificResult(value.scientific)||typeof value.stdout==='string'&&(value.error===undefined||typeof value.error==='string')&&(value.stderr===undefined||typeof value.stderr==='string'))?value:null;} catch{return null;}
 },[files,saved?.path]);
 const stale=!!output&&typeof output.code==='string'&&output.code!==code;
 const scientific=output?.scientific;
 const images=Array.isArray(output?.images)?output.images.filter(safeFigureUrl):[];
 function choose(file:File) {
  if(lock.current)return;
  const issue=pdfUploadError(file);if(issue){setError(issue);return;}
  setPdf(file);setLink('');setError('');setNotice('PDF selected. Analyze it to create a draft plan; no code will run.');
 }
 async function generate() {
  if(lock.current||(!pdf&&!link.trim()))return;
  lock.current=true;setBusy('Reading paper…');setError('');setNotice('');setProgress(null);setSyntax('');setSyntaxValid(null);
  try {
   let bytes:Uint8Array;let source:string;
   if(pdf){const issue=pdfUploadError(pdf);if(issue)throw new Error(issue);bytes=new Uint8Array(await pdf.arrayBuffer());source=pdf.name;}
   else {const fetched=await request<{data:string;source:string}>(base,'/api/replicate/paper',{url:link.trim()});bytes=Uint8Array.from(atob(fetched.data),character=>character.charCodeAt(0));source=fetched.source;}
   const text=await extractPdf(bytes,(page,total)=>{if(alive.current)setProgress({page,total});});
   if(!alive.current)return;
   setProgress(null);setBusy('Analyzing methodology and preparing a code draft…');
   const plan=await request<unknown>(base,'/api/replicate/plan',{text,source,focus});
   if(!alive.current)return;
   if(!isPlan(plan))throw new Error('The backend returned an incomplete plan. Your existing files have not been replaced.');
   const path=`replication/experiment-${crypto.randomUUID().slice(0,8)}.py`;
   const next={plan,path,source,paperText:text};setSaved(next);
   onSaveFiles([{path,content:plan.code},{path:manifest,content:JSON.stringify(next,null,2)}]);
   setBusy('Checking Python syntax without execution…');
   const check=await request<{valid:boolean;error?:string}>(base,'/api/tools/replicate',{action:'syntax',code:plan.code});
   if(!alive.current)return;
   setSyntaxValid(check.valid);setSyntax(check.valid?'Syntax checked. The experiment has not been executed.':check.error||'Syntax check failed. Review the generated code.');
   setNotice('Draft saved. Review the methodology, required inputs and code before requesting an approved execution.');
  } catch(reason) {if(alive.current)setError((reason as Error).message);}
  finally {lock.current=false;if(alive.current){setBusy('');setProgress(null);}}
 }
 const stage=busy?1:output&&!stale?4:saved?2:0;
 return <div className="replicate-studio science-studio">
  <div className="tool-eyebrow"><Copy size={12}/> PRE REPLICATE</div><h2>From paper to evidence</h2><p className="replicate-lead">Understand a method, review a reproducible plan, and keep proposed findings separate from measured results.</p>
  <ol className="science-stepper" aria-label="Replication workflow">{['Upload','Analyze','Review plan','Execute','Results'].map((name,index)=><li key={name} aria-current={index===stage?'step':undefined} className={index===stage?'is-current':index<stage&&index!==3?'is-past':''}><span>{index===1&&busy?<LoaderCircle size={14} className="spin"/>:index+1}</span><strong>{name}</strong>{index===3&&<small>Not connected</small>}</li>)}</ol>
  <section className="replicate-source" aria-label="Source paper">
   <div className={`science-dropzone ${dragging?'is-dragging':''}`} role="group" aria-label="PDF drop zone" aria-disabled={!!busy}
    onDragOver={event=>{event.preventDefault();if(!busy)setDragging(true);}}
    onDragLeave={event=>{if(!event.currentTarget.contains(event.relatedTarget as Node|null))setDragging(false);}}
    onDrop={event=>{event.preventDefault();setDragging(false);if(busy)return;if(event.dataTransfer.files.length!==1){setError('Choose one PDF at a time.');return;}choose(event.dataTransfer.files[0]);}}>
    <div className="science-upload-icon">{pdf?<FileText size={24}/>:<Upload size={24}/>}</div>
    <strong>{pdf?pdf.name:'Drop a research paper here'}</strong><p>{pdf?`${(pdf.size/1_000_000).toFixed(2)} MB · PDF · ready to analyze`:'Searchable PDF · up to 15 MB · up to 150 pages'}</p>
    <div><button type="button" className="outline-btn" disabled={!!busy} onClick={()=>upload.current?.click()}>{pdf?'Choose another PDF':'Browse files'}</button>{pdf&&<button type="button" className="icon-btn" aria-label="Remove selected PDF" disabled={!!busy} onClick={()=>{setPdf(null);setNotice('');}}><X size={16}/></button>}</div>
    <input ref={upload} type="file" accept="application/pdf,.pdf" hidden onChange={event=>{const file=event.target.files?.[0];if(file)choose(file);event.target.value='';}}/>
   </div>
   <div className="science-source-divider"><span>or use an arXiv paper</span></div>
   <label className="science-field" htmlFor="replicate-link">arXiv abstract or PDF link</label><input id="replicate-link" className="science-input" type="url" placeholder="https://arxiv.org/abs/…" value={link} disabled={!!busy} onChange={event=>{setLink(event.target.value);setPdf(null);setError('');}}/>
   <label className="science-field" htmlFor="replicate-focus">Experiment focus <span>Optional</span></label><textarea id="replicate-focus" placeholder="Which experiment or result would you like to investigate?" value={focus} disabled={!!busy} onChange={event=>setFocus(event.target.value)}/>
   <div className="replicate-source-footer"><span>Creates a reviewable plan and Python draft. No code is executed.</span><button className="primary-btn" disabled={!!busy||(!pdf&&!link.trim())} onClick={()=>void generate()}>{busy?<LoaderCircle size={14} className="spin"/>:<Code2 size={14}/>} {busy?'Analyzing…':'Analyze paper'}</button></div>
  </section>
  {busy&&<div className="science-feedback" role="status" aria-live="polite"><LoaderCircle size={16} className="spin"/><div><strong>{busy}</strong>{progress?<><p>Reading page {progress.page} of {progress.total}</p><progress value={progress.page} max={progress.total} aria-label="PDF pages extracted"/></>:<p>Waiting for the current operation. No estimated completion percentage is available.</p>}</div></div>}
  {error&&<div role="alert" className="science-feedback is-error"><AlertTriangle size={18}/><div><strong>Could not finish this step</strong><p>{error}</p><p>You can correct the input and retry. No experiment has been launched.</p></div></div>}
  {notice&&!busy&&<div role="status" className="science-feedback is-success"><CheckCircle2 size={17}/><p>{notice}</p></div>}
  {saved?<div className="replicate-split science-enter"><section className="replicate-plan"><span className="replicate-caption">DRAFT · RESEARCHER REVIEW REQUIRED</span><h3>{saved.plan.title}</h3><p>{saved.plan.summary}</p><h4>{saved.plan.experiment}</h4><p>{saved.plan.methodology}</p><ol>{saved.plan.steps.map((step,index)=><li key={index}>{step}</li>)}</ol><div className="science-reference"><h4>Expected results described by the paper</h4><p>{saved.plan.expected_results}</p><small>AI-extracted description. Verify source evidence; these are not measurements from PRE.</small></div>{[['Requirements',saved.plan.requirements],['Missing inputs',saved.plan.missing],['Limitations & assumptions',saved.plan.limitations]].map(([heading,items])=>(items as string[]).length>0&&<details className="science-details" open={heading==='Missing inputs'} key={heading as string}><summary>{heading as string} ({(items as string[]).length})</summary><ul>{(items as string[]).map((item,index)=><li key={index}>{item}</li>)}</ul></details>)}<small>Source: {saved.source}</small></section>
   <section className="replicate-code"><div className="replicate-code-header"><FileText size={14}/><span>{saved.path.split('/').pop()}</span><span className="spacer"/><button className="outline-btn" disabled={!!busy} onClick={()=>onInsert(code)} title="Insert a draft only; do not run untrusted code in the local notebook"><Plus size={13}/>Insert code draft</button></div>
    <Editor height="390px" language="python" theme="pearl" value={code} onChange={value=>{onSaveFiles([{path:saved.path,content:value||''}]);setSyntax('Code edited. Syntax has not been rechecked.');setSyntaxValid(null);}} options={{readOnly:!!busy,minimap:{enabled:false},fontSize:12,wordWrap:'on',automaticLayout:true,scrollBeyondLastLine:false}}/>
    <div className="replicate-code-note"><span className={`science-badge ${syntaxValid===false?'is-error':'is-neutral'}`}>{syntaxValid===true?'Syntax valid':syntaxValid===false?'Syntax issue':'Syntax unverified'}</span><p>{syntax||'Saved code draft. No syntax check is recorded for this version.'}</p><p>Syntax validation does not establish scientific validity, approval, or safe execution.</p></div>
    <div className="science-execution-gate"><LockKeyhole size={19}/><div><strong>Approved execution is not connected</strong><p>Generated code cannot be safely executed through the host notebook runtime. Backend integration must obtain explicit approval and use restricted workers.</p><button className="outline-btn" disabled>Execute · integration required</button></div></div>
    <div className="replicate-output"><h4>Recorded results <button className="outline-btn" disabled={!!busy||!output} onClick={onAnalyze}>Analyze with Ask AI</button></h4>{stale&&<p role="status" className="science-feedback is-warning">The code has changed. These historical results belong to the saved execution, not the current draft.</p>}
     {isScientificResult(scientific)?<ScientificResults result={scientific}/>:output?<><span className={`science-badge ${output.error?'is-error':'is-neutral'}`}>{output.error?'Recorded execution failed':'Recorded execution · scientific validity unverified'}</span>{typeof output.executedAt==='string'&&<p className="science-muted">Recorded at {output.executedAt}</p>}<pre className="science-console">{[output.stdout,output.stderr,output.error].filter(item=>typeof item==='string').join('\n')||'No text output was recorded.'}</pre>{images.map((image,index)=><figure className="science-notebook-figure" key={index}><img src={image} alt={`Recorded experiment figure ${index+1}`}/><figcaption>Recorded figure {index+1}</figcaption></figure>)}<p className="science-muted">No structured reference comparison is included in this legacy execution record.</p></>:<div className="science-empty compact"><FileText size={23}/><p>No measured results yet. A generated plan and valid syntax are not executed evidence.</p></div>}
    </div>
   </section></div>:<div className="science-empty"><FileText size={30}/><h3>Start with the paper, keep the evidence</h3><p>Upload a searchable PDF or paste an arXiv link. Review its proposed method, missing inputs and editable code here before any execution.</p></div>}
 </div>;
}
