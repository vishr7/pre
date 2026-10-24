import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
import {loadEnv} from 'vite';
import {prepare,scoreReview,digest} from './core.mjs';
import {reviewPaper} from '../../server/ai/review.mjs';
import {Runtime} from '../../server/runtime.mjs';
const [command='check',...args]=process.argv.slice(2);
const option=(name,fallback)=>{const i=args.indexOf(name);return i<0?fallback:args[i+1];};
const input=option('--input','evaluation/review-fixtures.jsonl');
const out=resolve(option('--out',`.runtime/evaluations/${command}-${Date.now()}`));
await mkdir(out,{recursive:true});
if(command==='format'){
 const runtime=new Runtime();const fixtures=JSON.parse(await readFile('evaluation/format-fixtures.json','utf8'));const reports=[];
 try{for(const fixture of fixtures){try{const result=await runtime.compile({sessionId:'format-evaluation',source:fixture.source,files:[]});const id=result.pdfUrl.split('/').pop();await writeFile(`${out}/${fixture.id}.pdf`,runtime.pdfs.get(id));await writeFile(`${out}/${fixture.id}.log`,result.logs||'');reports.push({id:fixture.id,compiled:true,layout_warnings:(result.logs||'').split('\n').filter(line=>/Overfull|Underfull|LaTeX Warning|Font Warning/.test(line)),visual_review_required:true});}catch(e){reports.push({id:fixture.id,compiled:false,error:e.message});}}}finally{await runtime.close();}
 await writeFile(`${out}/format-report.json`,JSON.stringify(reports,null,2));
 console.log(JSON.stringify({out,compiled:reports.filter(r=>r.compiled).length,total:reports.length}));if(reports.some(r=>!r.compiled))process.exitCode=1;
}else{
 const records=prepare((await readFile(input,'utf8')).split('\n').filter(line=>line.trim()).map(line=>JSON.parse(line)));
 if(command==='prepare'||command==='check'){
  for(const split of ['train','validation','test'])await writeFile(`${out}/${split}.jsonl`,records.filter(r=>r.split===split).map(r=>JSON.stringify(r)).join('\n'));
  await writeFile(`${out}/manifest.json`,JSON.stringify({input,records:records.length,input_sha256:digest(await readFile(input)),sources:[...new Set(records.map(r=>r.source))],licenses:[...new Set(records.map(r=>r.license))],note:'Splits group all versions/reviews by group_id. Verify rights and human reference quality before use.'},null,2));
  console.log(JSON.stringify({out,records:records.length,counts:Object.fromEntries(['train','validation','test'].map(split=>[split,records.filter(r=>r.split===split).length]))}));
 }else if(command==='review'){
  if(!args.includes('--live'))throw new Error('Add --live to send papers to Gemini and incur API usage. Use check for offline validation.');
  const env={...loadEnv('development',process.cwd(),''),...process.env};
  const split=option('--split','test');if(!['train','validation','test','all'].includes(split))throw new Error('Invalid split.');
  const limit=Number(option('--limit','5'));if(!Number.isInteger(limit)||limit<1||limit>100)throw new Error('Use a limit between 1 and 100.');
  const selected=records.filter(r=>split==='all'||r.split===split).slice(0,limit);if(!selected.length)throw new Error('No records in this split; use --split all for the synthetic smoke fixtures.');
  const results=[];let commit='unknown';try{commit=execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();}catch{}
  for(const [index,record] of selected.entries()){
   const start=Date.now();try{const review=await reviewPaper({latex:record.text,venue:record.venue||'generic'},{env});const result={id:record.id,split:record.split,paper_sha256:record.text_sha256,review,metrics:scoreReview(record,review),elapsed_ms:Date.now()-start};results.push(result);await writeFile(`${out}/review-${index+1}.json`,JSON.stringify(result,null,2));}catch(e){results.push({id:record.id,error:e.message});}
  }
  await writeFile(`${out}/report.json`,JSON.stringify({model:env.GEMINI_MODEL,commit,created_at:new Date().toISOString(),input_sha256:digest(await readFile(input)),pipeline:'Current PRE reviewer including arithmetic audit; evaluates post-validation output.',results},null,2));
  await writeFile(`${out}/human-review.jsonl`,results.filter(r=>r.review).flatMap(r=>r.review.comments.map(c=>JSON.stringify({paper_id:r.id,comment_id:c.id,quote:c.quote,comment:c.comment,suggestion:c.suggestion,supported:null,useful:null,severity_appropriate:null,notes:''}))).join('\n'));
  console.log(JSON.stringify({out,evaluated:results.length,failed:results.filter(r=>r.error).length}));if(results.some(r=>r.error))process.exitCode=1;
 }else throw new Error('Use check, prepare, review, or format.');
}
