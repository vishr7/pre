import { spawn } from 'node:child_process';
import { workerEnvironment } from './worker-env.mjs';
export function replicate(data, {python, cwd}) {
 if(!['compare','report','demo','syntax'].includes(data?.action))throw new Error('Choose a replication action.');
 return new Promise((resolve,reject)=>{
  const child=spawn(python,['-m','pre_science.ui_bridge'],{cwd,env:{...workerEnvironment(),MPLBACKEND:'Agg'},stdio:['pipe','pipe','pipe'],detached:process.platform!=='win32'});
  let output='',errors='',finished=false;
  const stop=()=>{try{if(process.platform!=='win32')process.kill(-child.pid,'SIGKILL');else child.kill('SIGKILL');}catch{}};
  const fail=error=>{if(finished)return;finished=true;clearTimeout(timer);stop();reject(error);};
  const timer=setTimeout(()=>fail(new Error('Replication timed out. Please try again.')),90000);
  child.on('error',()=>fail(new Error('Could not start the science Python environment. Install requirements-science-dev.txt.')));
  child.stdin.on('error',()=>{});
  child.stdout.on('data',chunk=>{output+=chunk;if(output.length>2000000)fail(new Error('Replication report exceeds the output limit.'));});
  child.stderr.on('data',chunk=>{errors=(errors+chunk).slice(-4000);});
  child.on('close',code=>{if(finished)return;finished=true;clearTimeout(timer);try{const result=JSON.parse(output);if(code!==0||(result.error && result.valid!==false))reject(new Error(result.error||'Replication failed.'));else resolve(result);}catch{reject(new Error(errors.includes('ModuleNotFoundError')?'Science dependencies are missing. Install requirements-science-dev.txt.':'Replication returned an invalid report.'));}});
  child.stdin.end(JSON.stringify(data));
 });
}
