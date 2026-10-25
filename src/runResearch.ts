import {batchCell,sshOnly} from './iterateBatch.ts';
import type {ResearchWorkflow} from './researchWorkflow';
import type {RemoteRunner} from './remoteRun';
export async function runResearch(plan:ResearchWorkflow,runner:RemoteRunner|null,request:(path:string,body:unknown)=>Promise<any>,progress:(text:string)=>void,wait=()=>new Promise<void>(r=>setTimeout(r,1200))){
 const configurations=JSON.parse(plan.configurations);
 if(runner){
  const location=runner.activeTitle();progress('Checking SSH connection…');
  const result=await runner.run(sshOnly(batchCell(plan.code,configurations,plan.metric,plan.direction,plan.parallel)),'python');
  if(result.cancelled||result.exitCode!==0)throw new Error('Terminal run stopped or failed. No local retry was started. '+result.output.slice(-2000));
  if(!result.output.split('\n').some(line=>line.trim()==='__PRE_NO_SSH__')){
   const line=result.output.split('\n').find(line=>line.startsWith('PRE_BATCH:'));
   if(!line)throw new Error('No results received from SSH. No local retry was started.');
   return {...JSON.parse(line.slice(10)),id:crypto.randomUUID(),code:plan.code,metric:plan.metric,direction:plan.direction,ranOn:location};
  }
 }
 if(plan.execution==='ssh')throw new Error('SSH is required. Connect your terminal, then try again. Nothing ran locally.');
 let job=await request('/api/iterate/start',{...plan,configurations,approved:true});
 while(job.status==='running'){
  progress(`Running locally · ${job.trials.filter((t:{status:string})=>!['queued','running'].includes(t.status)).length}/${job.trials.length} tests finished`);
  await wait();job=await request('/api/iterate/status',{id:job.id});
 }
 return {...job,ranOn:'Local'};
}
