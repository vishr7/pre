// Frontend contract/rendering checks; fixtures are unit-test data, not demo results.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

// Transpile the small browser-only view without adding a test framework or files.
const compiled = new Map();
async function sourceModule(url) {
 if(compiled.has(url.href))return compiled.get(url.href);
 let code=ts.transpileModule(await readFile(url,'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText;
 for(const match of [...code.matchAll(/from\s+(['"])([^'"]+)\1/g)]) {
  const specifier=match[2];
  const target=specifier.startsWith('.')?await sourceModule(new URL(specifier.replace(/\.(tsx?|js)$/,'')+'.'+(/ScientificResults|IteratePanel/.test(specifier)?'tsx':'ts'),url)):import.meta.resolve(specifier);
  code=code.replace(match[0],`from ${JSON.stringify(target)}`);
 }
 const data='data:text/javascript;base64,'+Buffer.from(code).toString('base64');compiled.set(url.href,data);return data;
}
const helpers=await import(await sourceModule(new URL('../src/scientific.ts',import.meta.url)));
const {default:Results}=await import(await sourceModule(new URL('../src/ScientificResults.tsx',import.meta.url)));
const {default:Tool}=await import(await sourceModule(new URL('../src/ScientificTool.tsx',import.meta.url)));

function record(updates={}) {
 return {result_id:null,result_type:'experiment',source_id:'unit-execution',status:'success',title:'Recorded experiment',summary:'Unit fixture evidence.',
  freshness:'unknown',metrics:[{name:'accuracy',value:0,role:'measurement'}],artifacts:[],parameters:null,warnings:[],limitations:[],
  provenance:{code_sha256:'a'.repeat(64)},evidence:{completeness:'complete'},dataset_references:[],source_version:null,created_at:null,
  original_payload:null,original_reference:null,next_actions:[],all_next_actions:[],...updates};
}
const render=result=>renderToStaticMarkup(React.createElement(Results,{result}));

test('unified contract validates finite metrics and does not confuse zero with missing',()=>{
 assert.equal(helpers.isScientificResult(record()),true);
 assert.equal(helpers.isScientificResult({metrics:[]}),false);
 assert.equal(helpers.isScientificResult(record({metrics:[{name:'bad',value:NaN,role:'measurement'}]})),false);
 assert.equal(helpers.isScientificResult(record({source_id:{path:'unsafe'}})),false);
 assert.equal(helpers.formatMetric(0),'0');assert.equal(helpers.formatMetric(null),'Unavailable');
});
test('results expose status, uncertainty and full-precision hover values',()=>{
 const html=render(record({freshness:'stale',metrics:[{name:'score',value:1/3,role:'measurement'}],warnings:['Missing evaluation data'],limitations:['Not independent validation']}));
 assert.match(html,/changed since execution/);assert.match(html,/Missing evaluation data/);assert.match(html,/Not independent validation/);
 assert.match(html,/0.3333333333333333/);assert.match(html,/Evidence: complete/);
 assert.match(render(record({metrics:[{name:'score',value:null,role:'measurement'}]})),/Unavailable/);
});
test('opaque figure references remain placeholders without explicit delivery URLs',()=>{
 const ref='a'.repeat(32)+'-'+'b'.repeat(32);
 const result=record({artifacts:[{artifact_reference:ref,artifact_type:'figure',mime_type:'image/png',sha256:'c'.repeat(64),size_bytes:100}]});
 const html=render(result);assert.match(html,/preview not connected/);assert.doesNotMatch(html,/<img/);
 const delivered=renderToStaticMarkup(React.createElement(Results,{result,artifactUrls:{[ref]:'/api/artifacts/'+ref}}));
 assert.match(delivered,/<img/);assert.match(delivered,/loading="lazy"/);
 for(const url of ['javascript:alert(1)','file:///private/a.png','C:\\private\\a.png','//other.test/a.png','/api/%2e%2e/private'])assert.equal(helpers.safeFigureUrl(url),false);
});
test('recorded optimization history renders zero objectives without simulated progress',()=>{
 const html=render(record({result_type:'optimization',parameters:{depth:2},original_payload:{request:{n_trials:5},trials:[{trial_number:0,objective_value:0,status:'success',suggested_parameters:{depth:2}}]}}));
 assert.match(html,/Best observed parameters/);assert.match(html,/stored history, not live progress/);assert.match(html,/<td>0<\/td>/);
 assert.match(html,/<progress value="1" max="5"/);
 assert.match(render(record({result_type:'optimization',original_reference:'record:1'})),/authorized original-record retrieval/);
});
test('action cards only offer requirement review and preserve blockers',()=>{
 const action={action_id:'test_robustness',title:'Draft seed evaluation',description:'Review only',action_type:'draft',eligible:true,reason:'Separate study',missing_inputs:['Researcher approval'],required_inputs:[],requires_approval:true,warnings:[],execution_authorized:false};
 const result=record({next_actions:[action],all_next_actions:[action,{...action,action_id:'blocked',eligible:false,title:'Blocked action'}]});
 assert.equal(helpers.isScientificResult(result),true);const html=render(result);
 assert.match(html,/Separate approval required/);assert.match(html,/Eligibility does not authorize execution/);assert.match(html,/Blocked action/);
 assert.equal(helpers.isScientificResult(record({next_actions:[{...action,execution_authorized:true}]})),false);
});
test('PDF selection rejects invalid and oversized files before upload',()=>{
 assert.equal(helpers.pdfUploadError({name:'paper.pdf',type:'application/pdf',size:1000}),null);
 assert.match(helpers.pdfUploadError({name:'paper.csv',type:'text/csv',size:1}),/PDF/);
 assert.match(helpers.pdfUploadError({name:'paper.pdf',type:'application/pdf',size:15_000_001}),/15 MB/);
 assert.match(helpers.pdfUploadError({name:'paper.pdf',type:'application/pdf',size:0}),/empty/);
});
test('unconnected Experiment and Iterate expose their backend requirements',()=>{
 const experiment=renderToStaticMarkup(React.createElement(Tool,{mode:'Experiment',base:'',files:[],cells:[],onSummary:()=>{throw new Error('No request on render');}}));
 assert.match(experiment,/Scientific execution is not connected/);assert.match(experiment,/Backend connection required/);
 const iterate=renderToStaticMarkup(React.createElement(Tool,{mode:'Iterate',base:'',files:[],cells:[],onSummary:()=>{throw new Error('No request on render');}}));
 assert.doesNotMatch(iterate,/Set the Backend API URL/);assert.match(iterate,/Review and start study/);assert.match(iterate,/disabled=""/);
});
test('replication requests only paper analysis and syntax, with no host execution route',async()=>{
 const source=await readFile(new URL('../src/ReplicatePanel.tsx',import.meta.url),'utf8');
 assert.doesNotMatch(source,/['"]\/api\/(execute|runtime\/reset)['"]/);
 assert.match(source,/action:'syntax'/);assert.match(source,/integration required/);assert.match(source,/getTextContent/);
 const css=await readFile(new URL('../src/scientific.css',import.meta.url),'utf8');
 assert.match(css,/prefers-reduced-motion:reduce/);assert.match(css,/animation:none!important/);
});
