import { useEffect, useRef, useState } from 'react';
import { FlaskConical, Layers3, LoaderCircle, LockKeyhole } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { request, type Cell, type ProjectFile } from './api';
import { isScientificResult, object } from './scientific';
import ScientificResults from './ScientificResults';
import IteratePanel from './BackendIteratePanel';

type Props={mode:'Experiment'|'Iterate';base:string;files:ProjectFile[];cells:Cell[];onSummary:(text:string)=>void};
export default function ScientificTool(props:Props) {
 return props.mode==='Iterate' ? <IteratePanel base={props.base} files={props.files}/> : <ExperimentTool {...props}/>;
}
function ExperimentTool({mode,base,files,cells,onSummary}:Props) {
 const [prompt,setPrompt] = useState(''); const [working,setWorking] = useState(false);
 const [response,setResponse] = useState<Record<string,unknown>|null>(null); const [error,setError] = useState('');
 const generation = useRef(0); const pending = useRef(false);
 useEffect(() => {generation.current++;setResponse(null);setError('');setWorking(false);pending.current=false;return()=>{generation.current++;};}, [mode,base]);
 async function submit() {
  if (!base || pending.current) return;
  pending.current=true;const token=++generation.current;setWorking(true);setError('');setResponse(null);
  try {
   const value = await request<unknown>(base,`/api/tools/${mode.toLowerCase()}`,{prompt,files,cells});
   if(token!==generation.current)return;
   if(!object(value)||typeof value.result!=='string')throw new Error('The backend returned an unsupported response. Expected a result summary; no measurements were inferred.');
   setResponse(value);onSummary(value.result);
  } catch(reason) {if(token===generation.current)setError((reason as Error).message);}
  finally {if(token===generation.current){pending.current=false;setWorking(false);}}
 }
 const scientific = response?.scientific;
 return <div className="tool-workspace science-tool"><div className="tool-eyebrow">{mode==='Experiment'?<FlaskConical size={13}/>:<Layers3 size={13}/>} PRE {mode.toUpperCase()}</div><h2>{mode==='Experiment'?'From a question to measured evidence':'Explore the next configuration'}</h2><p className="science-lead">{mode==='Experiment'?'Keep hypotheses, recorded metrics and execution evidence together.':'Review actual trial history, best observed parameters and the limitations of a bounded search.'}</p>
  <div className="science-workflow-cards"><article><span>01</span><strong>Define</strong><p>{mode==='Experiment'?'Code, dataset and parameters':'Objective, search space and budget'}</p></article><article><span>02</span><strong>Review & approve</strong><p>Explicit approval and restricted execution</p></article><article><span>03</span><strong>Inspect evidence</strong><p>{mode==='Experiment'?'Metrics, figures and provenance':'Recorded trials and best configuration'}</p></article></div>
  {!base ? <div className="science-unavailable" role="status"><LockKeyhole size={22}/><div><h3>Scientific execution is not connected</h3><p>{mode==='Experiment'?'Scientific experiment execution':'Parameter optimization'} is not available in the local application yet. No experiment has been launched.</p><p>This feature needs a connected scientific backend with explicit approval and isolated execution. Setting a backend URL alone does not establish those protections.</p></div></div> : <div className="science-unavailable"><LockKeyhole size={18}/><p>A custom backend is configured. This screen can request a proposal; approval, restricted execution and live progress must be implemented by that backend. Requesting a proposal does not authorize execution.</p></div>}
  <form className="science-request" onSubmit={event=>{event.preventDefault();void submit();}}><label htmlFor="science-question">{mode==='Experiment'?'Research question':'Iteration objective'}</label><textarea id="science-question" value={prompt} disabled={working} onChange={event=>setPrompt(event.target.value)} placeholder={mode==='Experiment'?'Describe the hypothesis, dataset and metrics you want to evaluate.':'Describe the parameter changes and objective you want to investigate.'}/><button className="primary-btn" disabled={!base||working||!prompt.trim()}>{working?<LoaderCircle size={14} className="spin"/>:<FlaskConical size={14}/>} {working?'Waiting for backend…':base?'Request proposal':'Backend connection required'}</button></form>
  {error && <div role="alert" className="science-feedback is-error"><strong>Request could not be completed</strong><p>{error}</p><p>Your project has not been changed. Review the backend configuration and try again.</p></div>}
  {working && <div className="science-loading" role="status" aria-live="polite"><p>Waiting for a real response. No execution percentage is available.</p><div className="science-skeleton-grid" aria-hidden="true"><span/><span/><span/></div></div>}
  {isScientificResult(scientific) ? <ScientificResults result={scientific}/> : response ? <section className="science-results science-enter"><h3>Backend response</h3><ReactMarkdown>{String(response.result)}</ReactMarkdown><p className="science-muted">{scientific ? 'The scientific payload is not the unified scientific_response contract; no metrics or trial history were inferred.' : 'No structured scientific evidence was included.'}</p></section> : !working && <div className="science-empty"><FlaskConical size={24}/><h3>{mode==='Experiment'?'No experiment results yet':'No optimization trials yet'}</h3><p>{mode==='Experiment'?'Measured values will appear after a connected, approved experiment returns a scientific report.':'Trial counts, objectives and best parameters appear only when the backend supplies actual records.'}</p></div>}
 </div>;
}
