import { useEffect, useMemo, useState, type MutableRefObject } from 'react';
import { formatMetric } from './scientific';
import type { ProjectFile } from './api';
import type { RemoteRunner } from './remoteRun';

type Trial = {number:number;params:Record<string,unknown>;metrics:Record<string,number>;status:string;progress:Array<Record<string,number>>;error:string|null;seed:number;duration:number|null};
type Study = {id:string;status:string;space:Space;remote:{session_id:string;project:string;venv:string|null;partition:string|null;account:string|null;conda_env:string|null}|null;via_terminal?:boolean;parent_study:string|null;parent_trial:number|null;parent_params:Record<string,unknown>|null;trials:Trial[];best:Trial|null};
type Analysis = {importance:Record<string,number>;coordinates:Array<{number:number;params:Record<string,unknown>;score:number}>};
type Connection = {session_id:string;status:string;prompts?:Array<{prompt:string;echo:boolean}>};
type Space = {objective:{metric:string;direction:'minimize'|'maximize'};params:Record<string,unknown>;strategy:string;n_trials:number;parallel:number;timeout_seconds:number;seed:number};
const example = JSON.stringify({objective:{metric:'val_accuracy',direction:'maximize'},params:{lr:{type:'float',low:0.00001,high:0.1,log:true},batch_size:{type:'categorical',choices:[16,32,64]}},strategy:'bayesian',n_trials:20,parallel:2,timeout_seconds:300,seed:42},null,2);

async function api<T>(base:string,path:string,method='GET',body?:unknown):Promise<T> {
 const response=await fetch(`${base.replace(/\/$/,'')}/iterate${path}`,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
 if(!response.ok){const value=await response.json().catch(()=>({detail:response.statusText}));throw new Error(typeof value.detail==='string'?value.detail:JSON.stringify(value.detail));}
 return response.json();
}

type Target='local'|'terminal'|'hpc';

export default function BackendIteratePanel({base,files,runner}:{base:string;files:ProjectFile[];runner?:MutableRefObject<RemoteRunner|null>}) {
 const scripts=files.filter(file=>file.path.endsWith('.py'));
 const [scriptPath,setScriptPath]=useState(scripts[0]?.path||'');
 const [spaceText,setSpaceText]=useState(example);
 const [study,setStudy]=useState<Study|null>(null);
 const [parent,setParent]=useState<{study:string;trial:number}|null>(null);
 const [suggestion,setSuggestion]=useState('');
 const [analysis,setAnalysis]=useState<Analysis|null>(null);
 const [logTrial,setLogTrial]=useState<number|null>(null);const [logs,setLogs]=useState<{stdout:string;stderr:string}|null>(null);
 const [target,setTarget]=useState<Target>(()=>{try{const saved=localStorage.getItem('pre.iterate.target');return saved==='terminal'||saved==='hpc'?saved:'local';}catch{return 'local';}});const useRemote=target==='hpc';
 useEffect(()=>{try{localStorage.setItem('pre.iterate.target',target);}catch{/* storage unavailable */}},[target]);const [sessionId,setSessionId]=useState('');const [username,setUsername]=useState('');const [password,setPassword]=useState('');const [challenge,setChallenge]=useState<Connection|null>(null);const [challengeAnswers,setChallengeAnswers]=useState<string[]>([]);
 const [remoteProject,setRemoteProject]=useState('iterate');const [remoteVenv,setRemoteVenv]=useState('');const [remotePartition,setRemotePartition]=useState('');const [remoteAccount,setRemoteAccount]=useState('');const [remoteConda,setRemoteConda]=useState('');
 const [working,setWorking]=useState(false);const [error,setError]=useState('');
 // null = checking. With an empty Backend API URL, Vite forwards /iterate and /hpc to the Python backend.
 const [backendUp,setBackendUp]=useState<boolean|null>(null);const [probe,setProbe]=useState(0);
 useEffect(()=>{setBackendUp(null);let live=true;fetch(`${base.replace(/\/$/,'')}/iterate/health`).then(r=>r.ok?r.json():null).then(body=>{if(live)setBackendUp(body?.status==='ok');}).catch(()=>{if(live)setBackendUp(false);});return()=>{live=false;};},[base,probe]);
 useEffect(()=>{if(!backendUp)return;const id=localStorage.getItem('pre.iterate.study');if(id)void api<Study>(base,`/studies/${id}`).then(setStudy).catch(()=>localStorage.removeItem('pre.iterate.study'));},[base,backendUp]);
 useEffect(()=>{if(study?.id)localStorage.setItem('pre.iterate.study',study.id);},[study?.id]);
 useEffect(()=>{if(study?.via_terminal)setTarget('terminal');if(study?.remote){setTarget('hpc');setSessionId(study.remote.session_id);setRemoteProject(study.remote.project);setRemoteVenv(study.remote.venv||'');setRemotePartition(study.remote.partition||'');setRemoteAccount(study.remote.account||'');setRemoteConda(study.remote.conda_env||'');}},[study?.id]);
 useEffect(()=>{setAnalysis(null);if(study?.id&&study.status==='COMPLETED')void api<Analysis>(base,`/studies/${study.id}/analysis`).then(setAnalysis).catch(()=>{});},[base,study?.id,study?.status]);
 useEffect(()=>{if(!study?.id||logTrial===null)return;const read=()=>void api<{stdout:string;stderr:string}>(base,`/studies/${study.id}/trials/${logTrial}/logs`).then(setLogs).catch(()=>{});read();const timer=setInterval(read,3000);return()=>clearInterval(timer);},[base,study?.id,logTrial]);
 const metric=study?.space.objective.metric;
 const completed=useMemo(()=>study?.trials.filter(t=>t.status==='COMPLETED').sort((a,b)=>study.space.objective.direction==='minimize'?a.metrics[study.space.objective.metric]-b.metrics[study.space.objective.metric]:b.metrics[study.space.objective.metric]-a.metrics[study.space.objective.metric])||[],[study]);
 useEffect(()=>{if(!backendUp||!study?.id||!['RUNNING','STOPPING'].includes(study.status))return;
  let socket:WebSocket|undefined;try{const url=new URL(base||'/',window.location.href);url.protocol=url.protocol==='https:'?'wss:':'ws:';url.pathname=`${url.pathname.replace(/\/$/,'')}/iterate/studies/${study.id}/live`;socket=new WebSocket(url);socket.onmessage=event=>{try{setStudy(JSON.parse(event.data));}catch{/* Keep last valid update. */}};}catch{/* Polling remains available. */}
  const timer=setInterval(()=>{void api<Study>(base,`/studies/${study.id}`).then(setStudy).catch(e=>setError(e.message));},3000);
  return()=>{clearInterval(timer);socket?.close();};
 },[base,study?.id,study?.status]);
 // Terminal studies: the browser takes each waiting trial, runs it in the SSH tab, and posts the output back.
 useEffect(()=>{if(!backendUp||!study?.id||!study.via_terminal||!['RUNNING','STOPPING'].includes(study.status))return;
  let live=true;const id=study.id;
  void (async()=>{while(live){
   let job:{number:number;code:string}|null=null;
   try{job=await api<{number:number;code:string}|null>(base,`/studies/${id}/terminal/next`);}catch{/* retry below */}
   if(!job){await new Promise(r=>setTimeout(r,1000));continue;}
   let result:{exit_code:number|null;output:string};
   try{if(!runner?.current)throw new Error('Open the terminal and connect with SSH first.');const value=await runner.current.run(job.code,'python');result={exit_code:value.exitCode,output:value.output};}
   catch(e){result={exit_code:null,output:(e as Error).message};}
   await api(base,`/studies/${id}/terminal/${job.number}`,'POST',result).catch(()=>{});
  }})();
  return()=>{live=false;};
 },[base,backendUp,study?.id,study?.status,study?.via_terminal]);
 async function connectHpc(answer=false){setWorking(true);setError('');try{const response=await fetch(`${base.replace(/\/$/,'')}/hpc/${answer?`connect/${challenge?.session_id}/respond`:'connect'}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(answer?{responses:challengeAnswers}:{username,password})});const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:JSON.stringify(value.detail));setPassword('');setChallengeAnswers([]);if(value.status==='connected'){setSessionId(value.session_id);setChallenge(null);}else{setChallenge(value);setChallengeAnswers((value.prompts||[]).map(()=>''));}}catch(e){setError((e as Error).message);}finally{setWorking(false);}}
 async function start(){
  setError('');const script=files.find(f=>f.path===scriptPath)?.content;
  if(!script){setError('Choose a Python project file.');return;}
  let space:Space;try{space=JSON.parse(spaceText);}catch{setError('Search space must be valid JSON.');return;}
  if(useRemote&&!sessionId){setError('Connect an HPC session or enter its session ID.');return;}
  if(target==='terminal'&&!runner?.current){setError('Open the terminal and connect with SSH first.');return;}
  const proposal={script,space,...(target==='terminal'?{via_terminal:true}:{}),...(useRemote?{remote:{session_id:sessionId,project:remoteProject,venv:remoteVenv||null,partition:remotePartition||null,account:remoteAccount||null,conda_env:remoteConda||null}}:{}),...(parent?{parent_study:parent.study,parent_trial:parent.trial}:{})};
  setWorking(true);
  try{
   const preview=await api<{digest:string;trials:number;parallel:number;execution:string}>(base,'/preview','POST',proposal);
   if(!window.confirm(`Run ${preview.trials} trials with up to ${preview.parallel} parallel slots using ${preview.execution}? The selected script will execute there.`))return;
   const result=await api<Study>(base,'/studies','POST',{...proposal,approval_digest:preview.digest});setStudy(result);setParent(null);setLogTrial(null);setLogs(null);
  }catch(e){setError((e as Error).message);}finally{setWorking(false);}
 }
 function branch(trial:Trial){
  if(!study)return;setParent({study:study.id,trial:trial.number});
  setSpaceText(JSON.stringify(study.space,null,2));
  window.scrollTo({top:0,behavior:'smooth'});
 }
 function confirmBest(){if(!study?.best)return;setParent({study:study.id,trial:study.best.number});setSpaceText(JSON.stringify({...study.space,params:Object.fromEntries(Object.entries(study.best.params).map(([name,value])=>[name,{type:'categorical',choices:[value]}])),strategy:'random',n_trials:3,parallel:1},null,2));setSuggestion('Repeat the best configuration three times with distinct PRE_TRIAL_SEED values. Review the pinned parameters and approve the new study.');window.scrollTo({top:0,behavior:'smooth'});}
 async function suggest(){if(!study)return;setWorking(true);setError('');try{const value=await api<{proposal:{space:Space;rationale:string}}>(base,`/studies/${study.id}/suggest`,'POST');setSuggestion(value.proposal.rationale);setSpaceText(JSON.stringify(value.proposal.space,null,2));if(study.best)setParent({study:study.id,trial:study.best.number});}catch(e){setError((e as Error).message);}finally{setWorking(false);}}
 let best:number|undefined;const history=(study?.trials||[]).map(t=>{const value=t.metrics?.[metric||''];if(t.status==='COMPLETED'&&typeof value==='number')best=best===undefined?value:study?.space.objective.direction==='minimize'?Math.min(best,value):Math.max(best,value);return best;});
 const finite=history.filter((v):v is number=>typeof v==='number');const low=Math.min(...finite),high=Math.max(...finite);
 const axes=study?Object.keys(study.space.params):[];
 const scores=analysis?.coordinates.map(c=>c.score)||[];const scoreLow=Math.min(...scores),scoreHigh=Math.max(...scores);
 const coordinateY=(name:string,value:unknown)=>{const spec=study?.space.params[name] as {type?:string;low?:number;high?:number;choices?:unknown[]}|undefined;if(!spec)return 100;if(spec.type==='categorical'){const index=(spec.choices||[]).findIndex(choice=>choice===value);return 100-80*index/Math.max(1,(spec.choices||[]).length-1);}return 100-80*(Number(value)-Number(spec.low))/(Number(spec.high)-Number(spec.low)||1);};
 return <div className="tool-workspace science-tool iterate-tool"><div className="tool-eyebrow">PRE ITERATE</div><h2>Optimize an experiment</h2><p className="science-lead">Choose a Python script, define a JSON search space, review the run, and inspect measured trials. The script must accept parameter flags and <code>--out</code>, then write <code>metrics.json</code> there. It may print JSON lines with an epoch and objective metric for live curves.</p>
  {backendUp===false&&<div className="science-unavailable"><p>Iterate needs the PRE Python backend. From the project folder run <code>backend/.venv/Scripts/uvicorn backend.main:app --port 8000</code> (macOS/Linux: <code>backend/.venv/bin/uvicorn</code>), keep the Backend API URL empty, then <button onClick={()=>setProbe(n=>n+1)}>check again</button>.</p></div>}
  <section className="iterate-remote"><fieldset className="iterate-target"><legend>Run trials on</legend><label><input type="radio" name="iterate-target" checked={target==='local'} onChange={()=>setTarget('local')}/> This computer</label><label><input type="radio" name="iterate-target" checked={target==='terminal'} onChange={()=>setTarget('terminal')}/> SSH terminal (uses the terminal's login)</label><label><input type="radio" name="iterate-target" checked={target==='hpc'} onChange={()=>setTarget('hpc')}/> HPC service (separate login, GPUs/SLURM)</label></fieldset>{target==='terminal'&&<p className="science-muted">Trials run one at a time in the active terminal tab{runner?.current?` (“${runner.current.activeTitle()}”)`:''} with its Python interpreter. Connect with SSH ▾ in the terminal first and keep PRE open while the study runs. Files go to <code>~/pre-iterate/</code> on that machine.</p>}{useRemote&&<>
   <label>HPC session ID<input className="science-input" value={sessionId} onChange={e=>setSessionId(e.target.value)} placeholder="Existing connected session ID"/></label>
   <p>Connect to the configured HPC host:</p><div className="iterate-connect"><input className="science-input" aria-label="SSH username" value={username} onChange={e=>setUsername(e.target.value)} placeholder="Username"/><input className="science-input" type="password" aria-label="SSH password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="Password"/><button disabled={!backendUp||!username||!password||working} onClick={()=>void connectHpc()}>Connect</button></div>
   {challenge&&<div className="science-feedback"><div>{(challenge.prompts||[]).map((prompt,index)=><label key={index}>{prompt.prompt}<input className="science-input" type={prompt.echo?'text':'password'} value={challengeAnswers[index]||''} onChange={event=>setChallengeAnswers(current=>current.map((value,i)=>i===index?event.target.value:value))}/></label>)}</div><button disabled={challengeAnswers.some(value=>!value)||working} onClick={()=>void connectHpc(true)}>Respond</button></div>}
   <label>Remote project<input className="science-input" value={remoteProject} onChange={e=>setRemoteProject(e.target.value)}/></label><label>Workstation venv (optional)<input className="science-input" value={remoteVenv} onChange={e=>setRemoteVenv(e.target.value)}/></label><label>SLURM partition (optional)<input className="science-input" value={remotePartition} onChange={e=>setRemotePartition(e.target.value)}/></label><label>SLURM account (optional)<input className="science-input" value={remoteAccount} onChange={e=>setRemoteAccount(e.target.value)}/></label><label>SLURM conda env (optional)<input className="science-input" value={remoteConda} onChange={e=>setRemoteConda(e.target.value)}/></label>
  </>}</section>
  <div className="science-request"><label htmlFor="iterate-script">Experiment script</label><select className="science-input" id="iterate-script" value={scriptPath} onChange={e=>setScriptPath(e.target.value)}><option value="">Choose a Python file</option>{scripts.map(file=><option key={file.path} value={file.path}>{file.path}</option>)}</select><label htmlFor="iterate-space">Search space JSON</label><textarea id="iterate-space" value={spaceText} onChange={e=>setSpaceText(e.target.value)} spellCheck={false}/>{suggestion&&<div className="science-feedback"><strong>Suggested next round</strong><p>{suggestion}</p><p>Review and edit the JSON above before approving a new study.</p></div>}{parent&&<div className="science-feedback">Branching from trial {parent.trial} of {parent.study}. Edit the search space before starting; the parent configuration will run first when it fits the new space. <button onClick={()=>setParent(null)}>Clear branch</button></div>}<button className="primary-btn" disabled={!backendUp||!scriptPath||working} onClick={()=>void start()}>{working?'Preparing study…':'Review and start study'}</button></div>
  {error&&<div role="alert" className="science-feedback is-error">{error}</div>}
  {study&&<section className="science-results"><header className="science-result-heading"><div><span className="science-eyebrow">STUDY {study.id.slice(0,8)}</span><h3>{study.status.toLowerCase()}</h3></div><div>{study.status==='RUNNING'&&<button className="outline-btn" onClick={()=>void api<Study>(base,`/studies/${study.id}/stop`,'POST').then(setStudy).catch(e=>setError(e.message))}>Stop after active trials</button>}{completed.length>=2&&<button className="outline-btn" disabled={working} onClick={()=>void suggest()}>Suggest next round</button>}{study.best&&study.status==='COMPLETED'&&<button className="outline-btn" onClick={confirmBest}>Repeat best ×3</button>}</div></header><p className="science-muted">{study.trials.length} of {study.space.n_trials} trials recorded · {completed.length} completed · {study.trials.filter(t=>t.status==='FAILED').length} failed</p><progress value={study.trials.filter(t=>t.status!=='RUNNING').length} max={study.space.n_trials}/>
   {study.best&&<div className="science-metrics"><article className="science-metric"><span>Best {metric}</span><strong>{formatMetric(study.best.metrics[metric!])}</strong><small>Trial {study.best.number}</small></article><article className="science-metric"><span>Best parameters</span><code>{JSON.stringify(study.best.params)}</code></article></div>}
   {completed.length===3&&study.space.n_trials===3&&Object.values(study.space.params).every(value=>{const p=value as {type?:string;choices?:unknown[]};return p.type==='categorical'&&p.choices?.length===1;})&&<div className="science-metric"><span>Three-seed confirmation · mean ± sample standard deviation</span><strong>{(()=>{const scores=completed.map(t=>t.metrics[metric!]);const mean=scores.reduce((a,b)=>a+b,0)/3;const deviation=Math.sqrt(scores.reduce((sum,v)=>sum+(v-mean)**2,0)/2);return `${formatMetric(mean)} ± ${formatMetric(deviation)}`;})()}</strong></div>}
   {finite.length>1&&<div className="iterate-chart"><strong>Optimization history</strong><svg viewBox="0 0 600 120" role="img" aria-label="Best objective by trial"><polyline fill="none" stroke="#a35f7b" strokeWidth="2" points={history.map((v,i)=>`${20+i*560/Math.max(1,history.length-1)},${100-80*((v??low)-low)/(high-low||1)}`).join(' ')}/></svg></div>}
   {analysis&&Object.keys(analysis.importance).length>0&&<div className="iterate-chart"><strong>Parameter importance</strong>{Object.entries(analysis.importance).map(([name,value])=><div className="iterate-importance" key={name}><span>{name}</span><progress value={value} max={1}/><span>{Math.round(value*100)}%</span></div>)}</div>}
   {analysis&&analysis.coordinates.length>1&&axes.length>1&&<div className="iterate-chart"><strong>Parallel coordinates</strong><svg viewBox="0 0 600 130" role="img" aria-label="Trial parameters as parallel coordinates, colored by objective score">{axes.map((name,i)=><g key={name}><line x1={25+i*550/(axes.length-1)} x2={25+i*550/(axes.length-1)} y1="20" y2="100" stroke="#ddcbd6"/><text x={25+i*550/(axes.length-1)} y="120" textAnchor="middle" fontSize="9" fill="#705669">{name}</text></g>)}{analysis.coordinates.map(row=><polyline key={row.number} fill="none" stroke={`hsl(${330-100*(row.score-scoreLow)/(scoreHigh-scoreLow||1)} 45% 48%)`} strokeWidth="1.5" opacity="0.65" points={axes.map((name,i)=>`${25+i*550/(axes.length-1)},${coordinateY(name,row.params[name])}`).join(' ')}/>)}</svg><p>Each line is a completed trial; color follows the recorded objective.</p></div>}
   {study.trials.length>0&&<Wheel study={study} onBranch={branch}/>}
   {study.trials.some(t=>t.status==='RUNNING'&&t.progress.length>0)&&<div className="iterate-chart"><strong>Live learning curves</strong>{study.trials.filter(t=>t.status==='RUNNING').map(t=><p key={t.number}>Trial {t.number}: {t.progress.length} epoch updates · latest {metric}: {formatMetric(t.progress.at(-1)?.[metric!]??null)}</p>)}</div>}
   <div className="science-table-wrap"><table className="science-table"><thead><tr><th>Trial</th><th>Status</th><th>{metric}</th><th>Parameters</th><th>Seed</th><th>Action</th></tr></thead><tbody>{[...study.trials].sort((a,b)=>{const ai=completed.indexOf(a),bi=completed.indexOf(b);return ai<0&&bi<0?a.number-b.number:ai<0?1:bi<0?-1:ai-bi;}).map(t=><tr key={t.number}><td>{t.number}</td><td title={t.error||''}>{t.status}{t.error&&` · ${t.error}`}</td><td>{typeof t.metrics?.[metric!]==='number'?formatMetric(t.metrics[metric!]):'—'}</td><td><code>{JSON.stringify(t.params)}</code></td><td>{t.seed}</td><td><button onClick={()=>{setLogTrial(t.number);setLogs(null);}}>Logs</button>{t.status==='COMPLETED'&&<button onClick={()=>branch(t)}>Branch</button>}</td></tr>)}</tbody></table></div>
   {logTrial!==null&&<details className="science-details" open><summary>Trial {logTrial} logs</summary><button onClick={()=>setLogTrial(null)}>Close logs</button><h4>stdout</h4><pre>{logs?.stdout||'No output recorded yet.'}</pre><h4>stderr</h4><pre>{logs?.stderr||'No error output recorded.'}</pre></details>}
   <details className="science-details"><summary>Provenance and files</summary><p>Each trial has its own directory, a script SHA-256, package versions, logs, metrics, and seed. Runner files are stored under the Python backend’s data/iterate directory.</p></details>
  </section>}
 </div>;
}

function Wheel({study,onBranch}:{study:Study;onBranch:(trial:Trial)=>void}){
 const nodes=study.trials.slice(0,24);const metric=study.space.objective.metric;
 const scores=nodes.filter(t=>t.status==='COMPLETED').map(t=>t.metrics[metric]);const low=Math.min(...scores),high=Math.max(...scores);
 const baseline=study.parent_params||study.trials[0]?.params||{};
 return <details className="science-details"><summary>Experiment wheel · {nodes.length} trials{study.trials.length>nodes.length?' shown of '+study.trials.length:''}</summary><svg className="iterate-wheel" viewBox="0 0 320 320" role="img" aria-label="Radial view of the study's trials and their parameter changes"><circle cx="160" cy="160" r="22" fill="#f2e4ec" stroke="#b889a3"/><text x="160" y="164" textAnchor="middle" fontSize="10" fill="#705669">{study.parent_trial===null?'Study':`Parent ${study.parent_trial}`}</text>{nodes.map((trial,index)=>{const angle=2*Math.PI*index/nodes.length-Math.PI/2;const x=160+125*Math.cos(angle),y=160+125*Math.sin(angle);const changed=Object.keys(trial.params).filter(name=>JSON.stringify(trial.params[name])!==JSON.stringify(baseline[name]));const score=trial.metrics?.[metric];const color=trial.status==='COMPLETED'?`hsl(${330-100*(score-low)/(high-low||1)} 45% 48%)`:'#bbb0b8';return <g key={trial.number}><line x1="160" y1="160" x2={x} y2={y} stroke="#d9c6d1"/><title>{changed.length?`Changed ${changed.join(', ')}`:'Baseline configuration'}</title><circle cx={x} cy={y} r="12" fill={color} role={trial.status==='COMPLETED'?'button':undefined} tabIndex={trial.status==='COMPLETED'?0:undefined} onClick={()=>trial.status==='COMPLETED'&&onBranch(trial)} onKeyDown={event=>{if(trial.status==='COMPLETED'&&(event.key==='Enter'||event.key===' '))onBranch(trial);}}/><text x={x} y={y+3} textAnchor="middle" fontSize="9" fill="white" pointerEvents="none">{trial.number}</text></g>;})}</svg><p>Select a completed node to branch. Edge tooltips list parameters changed from the parent configuration.</p></details>;
}
