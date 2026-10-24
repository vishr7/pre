import { figureAssets } from './figureAssets.ts';
import type { Cell, ProjectFile } from './api';
const clip=(text:unknown,limit:number)=>typeof text==='string'&&text.length>limit?text.slice(0,limit)+'\n[Truncated for chat]':text;
const parse=(text?:string)=>{try{return JSON.parse(text||'null');}catch{return null;}};
export function assistantContext({cells,files,review,logs,compileError,selected,toolResult}:{cells:Cell[];files:ProjectFile[];review:unknown;logs:string;compileError:string;selected:string|null;toolResult:string}){
 const figures:{label:string;mimeType:string;data:string}[]=[];
 function addFigures(images:unknown,label:string){if(!Array.isArray(images))return;for(const [i,url] of images.entries()){
 if(figures.length>=2)break;
 if(typeof url!=='string')continue;const match=/^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+=*)$/.exec(url);
 if(match&&match[2].length<=1000000)figures.push({label:`${label}, figure ${i+1}`,mimeType:match[1],data:match[2]});
 }}
 const manifest=parse(files.find(file=>file.path==='replication/latest-plan.json')?.content);
 const runPath=typeof manifest?.path==='string'?manifest.path.replace(/\.py$/,'.results.json'):null;
 const run=parse(files.find(file=>file.path===runPath)?.content);
 if(run)addFigures(run.images,'Latest replication run');
 const replication=manifest?{source:manifest.source,plan:manifest.plan,paperText:clip(manifest.paperText,45000),codePath:manifest.path,
 currentCode:clip(files.find(file=>file.path===manifest.path)?.content,25000),
 latestRun:run?{executedAt:run.executedAt,source:run.source,executedCode:clip(run.code,25000),stdout:clip(run.stdout,20000),stderr:clip(run.stderr,8000),error:clip(run.error,8000),durationMs:run.durationMs,figureCount:run.images?.length||0,codeChangedSinceRun:run.code!==files.find(file=>file.path===manifest.path)?.content}:null}:null;
 const notebook=cells.map(cell=>{addFigures(cell.images,`Notebook cell ${cell.id}`);return {id:cell.id,type:cell.type,source:clip(cell.source,12000),output:clip(cell.output,8000),error:clip(cell.error,4000),status:cell.status,executionCount:cell.executionCount,figureCount:cell.images?.length||0,outputMatchesCurrentSource:cell.executedSource===undefined?null:cell.source===cell.executedSource};});
 const safeFiles=files.filter(file=>!file.path.startsWith('replication/')&&!/(^|\/)(\.env(?:\..*)?|.*\.(pem|key))$/i.test(file.path)).sort((a,b)=>Number(b.path===selected)-Number(a.path===selected)).slice(0,30).map(file=>({path:file.path,content:clip(file.content,10000)}));
 const context:Record<string,unknown>={availableFigurePaths:figureAssets(cells,files).map(asset=>asset.path),replication,review,notebook,files:safeFiles,selected,compilation:{error:compileError,logs:clip(logs,6000)},otherToolResult:clip(toolResult,12000),figureLabels:figures.map(f=>f.label)};
 // Bound text recursively without turning saved PNGs into enormous text prompts.
 let budget=190000;
 function bounded(value:unknown):unknown{
 if(typeof value==='string'){const limit=Math.min(45000,Math.max(0,budget));budget-=Math.min(limit,value.length);return clip(value,limit);}
 if(Array.isArray(value))return value.map(bounded);
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,bounded(item)]));
 return value;
 }
 return {...bounded(context) as Record<string,unknown>,figures};
}
