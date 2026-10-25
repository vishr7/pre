import type {ResearchWorkflow} from './researchWorkflow';
import type {MutableRefObject} from 'react';
import type {RemoteRunner} from './remoteRun';
import {batchCell,sshOnly} from './iterateBatch';
import {useEffect,useRef,useState} from 'react';
import Editor from '@monaco-editor/react';
import {request,type ProjectFile} from './api';
type Trial={index:number;parameters:Record<string,unknown>;status:string;metrics?:Record<string,number>;error?:string;stdout?:string};
type Job={id:string;status:string;code:string;metric:string;direction:string;ranOn?:string;trials:Trial[];best:Trial|null};
const savedPath='iteration/latest-results.json';
export default function IteratePanel({workflow,onReport,remoteRunner,initialPrompt,files,context,onSave,onInsert,onAnalyze}:{workflow:(ResearchWorkflow&{id:string})|null;onReport:(report:Job)=>void;remoteRunner:MutableRefObject<RemoteRunner|null>;initialPrompt:string;files:ProjectFile[];context:unknown;onSave:(files:ProjectFile[])=>void;onInsert:(code:string)=>void;onAnalyze:()=>void}){
 const [prompt,setPrompt]=useState(initialPrompt||'');
 const [code,setCode]=useState(files.find(f=>f.path==='iteration/trial.py')?.content||'def run_trial(params):\n    # Return measured metrics, for example {"loss": value}\n    raise NotImplementedError("Generate or write your experiment first")');
 const [grid,setGrid]=useState(files.find(f=>f.path==='iteration/configurations.json')?.content||'[{"learning_rate":0.01,"seed":42},{"learning_rate":0.08,"seed":42}]');
 const [metric,setMetric]=useState('loss');const [direction,setDirection]=useState('minimize');const [parallel,setParallel]=useState(2);
 const [ready,setReady]=useState(!!files.find(f=>f.path==='iteration/trial.py'));
 const [remoteBusy,setRemoteBusy]=useState(false);
 const [summary,setSummary]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false);
 const [job,setJob]=useState<Job|null>(()=>{try{return JSON.parse(files.find(f=>f.path===savedPath)?.content||'null');}catch{return null;}});
 const saveRef=useRef(onSave);saveRef.current=onSave;
 const reportRef=useRef(onReport);reportRef.current=onReport;
 const analyzeRun=useRef(false);
 const [execution,setExecution]=useState<'auto'|'ssh'>('auto');
 const [writeAnalysis,setWriteAnalysis]=useState(false);
 const appliedWorkflow=useRef('');
 useEffect(()=>{if(!workflow||appliedWorkflow.current===workflow.id||remoteBusy||job?.status==='running')return;appliedWorkflow.current=workflow.id;setReady(true);setCode(workflow.code);setGrid(workflow.configurations);setMetric(workflow.metric);setDirection(workflow.direction);setParallel(workflow.parallel);setExecution(workflow.execution);setWriteAnalysis(workflow.writeAnalysis);setSummary(workflow.summary);setPrompt(initialPrompt);},[workflow?.id,remoteBusy,job?.status]);
 useEffect(()=>{if(!job||job.status!=='running')return;let active=true;let timer:ReturnType<typeof setTimeout>;const poll=async()=>{try{const next=await request<Job>('','/api/iterate/status',{id:job.id});if(active){setJob(next);saveRef.current([{path:savedPath,content:JSON.stringify(next,null,2)}]);if(next.status==='running')timer=setTimeout(poll,1500);else if(next.status==='completed'&&analyzeRun.current){analyzeRun.current=false;reportRef.current(next);}}}catch(e){if(active)setError((e as Error).message);}};timer=setTimeout(poll,1000);return()=>{active=false;clearTimeout(timer);};},[job?.id,job?.status]);
 const running=job?.status==='running'||remoteBusy;
 async function generate(){setBusy(true);setError('');try{const r=await request<{code:string;configurations:string;summary:string;metric:string;direction:string}>('','/api/iterate/plan',{prompt,context});setReady(true);setCode(r.code);setGrid(JSON.stringify(JSON.parse(r.configurations),null,2));setMetric(r.metric);setDirection(r.direction);setSummary(r.summary);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 function bundle(){const configurations=JSON.parse(grid);if(!Array.isArray(configurations)||!configurations.length||configurations.length>32||configurations.some(c=>!c||typeof c!=='object'||Array.isArray(c)))throw new Error('Use 1–32 configurations.');return configurations;}
 function saveDraft(){const configurations=bundle();const driver=`import json, os\nfrom trial import run_trial\nwith open('configurations.json') as f: configs = json.load(f)\ni = int(os.environ.get('SLURM_ARRAY_TASK_ID', '0'))\nmetrics = run_trial(configs[i])\nos.makedirs('results', exist_ok=True)\nwith open(f'results/{i}.json', 'w') as f: json.dump({'parameters': configs[i], 'metrics': metrics}, f, allow_nan=False)\nprint(json.dumps(metrics, allow_nan=False))\n`;onSave([{path:'iteration/trial.py',content:code},{path:'iteration/configurations.json',content:JSON.stringify(configurations,null,2)},{path:'iteration/run_trial.py',content:driver},{path:'iteration/submit.slurm',content:`#!/bin/bash\n#SBATCH --job-name=pre-iterate\n#SBATCH --array=0-${configurations.length-1}%${parallel}\n#SBATCH --time=00:10:00\n#SBATCH --cpus-per-task=1\n#SBATCH --mem=2G\n# Add your cluster account/partition and activate its Python environment.\n# Submit from the directory containing trial.py and configurations.json.\nset -euo pipefail\npython3 run_trial.py\n`}]);return configurations;}
 async function start(){analyzeRun.current=writeAnalysis;setBusy(true);setError('');try{const configurations=saveDraft();
 if(!metric.trim()||!['minimize','maximize'].includes(direction))throw new Error('Choose an objective metric and direction.');
 if(!Number.isInteger(parallel)||parallel<1||parallel>4)throw new Error('Choose 1–4 workers.');
 const runner=remoteRunner.current;
 const executionTitle=runner?.activeTitle()||'Local';
 if(runner){
  setRemoteBusy(true);setSummary('Checking the active terminal for SSH…');
  const remote=await runner.run(sshOnly(batchCell(code,configurations,metric,direction,parallel)),'python');
  if(remote.cancelled)throw new Error('SSH batch interrupted. No local retry was started.');
  if(remote.exitCode!==0)throw new Error('SSH terminal execution failed. No local retry was started. '+remote.output.slice(-2000));
  if(!remote.output.split('\n').some(line=>line.trim()==='__PRE_NO_SSH__')){
   const line=remote.output.split('\n').find(line=>line.startsWith('PRE_BATCH:'));
   if(!line)throw new Error('SSH returned no batch report. No local retry was started.');
   const next={...JSON.parse(line.slice(10)),id:crypto.randomUUID(),code,metric,direction,ranOn:executionTitle};
   setJob(next);onSave([{path:savedPath,content:JSON.stringify(next,null,2)}]);setSummary('Batch ran through SSH on '+executionTitle);if(analyzeRun.current){analyzeRun.current=false;reportRef.current(next);}return;
  }
 }
 if(execution==='ssh')throw new Error('This workflow requires SSH. Connect and select an SSH terminal, then Run again. Nothing ran locally.');
 setRemoteBusy(false);setSummary('No SSH environment detected in the active terminal. Running locally.');
 const next=await request<Job>('','/api/iterate/start',{code,configurations,metric,direction,parallel,approved:true});setJob(next);onSave([{path:savedPath,content:JSON.stringify(next,null,2)}]);}catch(e){setError((e as Error).message);}finally{setBusy(false);setRemoteBusy(false);}}
 return <div className="tool-workspace science-tool iterate-simple">
 <div className="tool-eyebrow">PRE ITERATE</div><h2>What would you like to test?</h2><p>Describe your idea. AI prepares the code, compares the settings, and helps explain the results.</p>
 <label className="iterate-question">Your question<textarea placeholder="For example: which learning rate works best for my model?" value={prompt} onChange={e=>setPrompt(e.target.value)} disabled={busy||running}/></label>
 <button className="primary-btn" onClick={()=>void generate()} disabled={busy||running||!prompt.trim()}>{busy&&!running?'Preparing…':ready?'Update plan':'Make a test plan'}</button>
 {error&&<p role="alert" className="science-feedback is-error">{error}</p>}
 {ready&&<section className="iterate-plan"><div className="iterate-step">YOUR TEST PLAN</div><h3>Compare {(()=>{try{return bundle().length;}catch{return 'your';}})()} different settings</h3><p>{summary||'Your saved experiment is ready to review and run.'}</p><div className="workflow-meta"><span>Measure: {metric}</span><span>{direction==='minimize'?'Lower is better':'Higher is better'}</span><span>{execution==='ssh'?'SSH required':'SSH if connected · otherwise local'}</span></div>
 <details className="iterate-disclosure"><summary>View or edit the code</summary><article className="cell python"><div className="cell-header"><strong>Python experiment</strong><span className="spacer"/><button disabled={busy||running} onClick={()=>{try{onInsert(code+'\n\nimport json\nprint(run_trial(json.loads('+JSON.stringify(JSON.stringify(bundle()[0]))+')))');}catch(e){setError((e as Error).message);}}}>Add to notebook</button></div><Editor height="300px" language="python" theme="pearl" value={code} onChange={v=>setCode(v||'')} options={{readOnly:busy||running,minimap:{enabled:false},automaticLayout:true,scrollBeyondLastLine:false,scrollbar:{alwaysConsumeMouseWheel:false}}}/></article></details>
 <details className="iterate-disclosure"><summary>Advanced settings</summary><label>Settings to compare (JSON)<textarea rows={7} value={grid} onChange={e=>setGrid(e.target.value)} disabled={busy||running}/></label><div className="iterate-options"><label>What to measure<input value={metric} onChange={e=>setMetric(e.target.value)} disabled={busy||running}/></label><label>Best result<select value={direction} onChange={e=>setDirection(e.target.value)} disabled={busy||running}><option value="minimize">Lowest value</option><option value="maximize">Highest value</option></select></label><label>Tests at once<input type="number" min={1} max={4} value={parallel} onChange={e=>setParallel(Number(e.target.value))} disabled={busy||running}/></label><label>Run on<select value={execution} onChange={e=>setExecution(e.target.value as 'auto'|'ssh')} disabled={busy||running}><option value="auto">Connected SSH or this computer</option><option value="ssh">SSH only</option></select></label></div><p>Each test has 30 seconds. Code runs directly on the selected machine; required packages and data must already be available.</p><details><summary>Full execution script</summary><pre>{(()=>{try{return batchCell(code,bundle(),metric,direction,parallel);}catch{return 'Check the settings JSON.';}})()}</pre></details><button className="outline-btn" disabled={busy||running} onClick={()=>{try{saveDraft();setSummary('Saved the code and cluster job script in iteration/.');}catch(e){setError((e as Error).message);}}}>Export cluster job</button></details>
 <label className="iterate-check"><input type="checkbox" checked={writeAnalysis} onChange={e=>setWriteAnalysis(e.target.checked)} disabled={busy||running}/>Draft a paper analysis when the tests finish</label><p className="iterate-hint">You review any paper edits before they are applied.</p>
 <div className="iterate-run"><button className="primary-btn" disabled={busy||running} onClick={()=>void start()}>{running?'Running tests…':'Run tests'}</button>{running&&!remoteBusy&&<button className="outline-btn" onClick={async()=>{try{const stopped=await request<Job>('','/api/iterate/cancel',{id:job?.id});setJob(stopped);onSave([{path:savedPath,content:JSON.stringify(stopped,null,2)}]);}catch(e){setError((e as Error).message);}}}>Stop</button>}{remoteBusy&&<span role="status">Running in the active terminal. Press Ctrl+C there to stop.</span>}</div></section>}
 {job&&<section className="science-results"><div className="iterate-step">RESULTS</div><h3>{job.status==='completed'?'Tests finished':job.status==='running'?'Testing your settings…':'Tests stopped'}</h3><p>{job.trials.filter(t=>!['queued','running'].includes(t.status)).length} of {job.trials.length} finished · {job.ranOn||'Local'}</p>{job.code!==code&&<p className="science-feedback is-warning">These results are from an earlier version of the code.</p>}{job.best&&<p>Best measured {job.metric}: <strong>{job.best.metrics?.[job.metric].toExponential(5)}</strong>. This is the best result among the settings tested.</p>}<button className="primary-btn" disabled={running} onClick={onAnalyze}>Explain results with AI</button><details className="iterate-disclosure"><summary>See individual test results</summary>{job.trials.map(t=><details key={t.index}><summary>Test {t.index+1} · {t.status}</summary><pre>{JSON.stringify(t.parameters,null,2)}{'\n'}{JSON.stringify(t.metrics,null,2)}{'\n'}{t.error||t.stdout||'Waiting for execution'}</pre></details>)}</details></section>}
 </div>;
}
