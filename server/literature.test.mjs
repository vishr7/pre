import test from 'node:test';
import assert from 'node:assert/strict';
import {searchLiterature} from './literature.mjs';
import {citationAudit} from '../src/citations.ts';
test('citation audit checks fragments, optional citation arguments and bibliography definitions',()=>{
 const files=[{path:'main.tex',content:String.raw`\citep[see][p. 3]{known,missing} % \cite{ignored}
\bibitem{inline} A reference. \cite{inline}`},{path:'refs.bib',content:'@article{known, title={Example}}\n@book{known, title={Duplicate}}'}];
 const result=citationAudit(files,[{id:'fragment',type:'latex',source:String.raw`\autocite{another}`},{id:'linked',type:'latex',filePath:'main.tex',source:files[0].content}]);
 assert.deepEqual(result.missing,['missing','another']);assert.deepEqual(result.duplicates,['known']);assert.equal(result.cited.includes('ignored'),false);
});
test('literature search returns source identifiers and evidence limits, without inventing abstracts',async()=>{
 const result=await searchLiterature({query:'attention methods'},async url=>{
 assert.equal(url.hostname,'api.crossref.org');assert.equal(url.searchParams.get('rows'),'8');
 return {ok:true,json:async()=>({message:{items:[{DOI:'10.1234/test',title:['A <i>method</i>'],author:[{given:'A',family:'Researcher'}],published:{'date-parts':[[2024]]}} ]}})};
 });
 assert.equal(result.papers[0].title,'A method');assert.equal(result.papers[0].evidence,'metadata only');assert.equal(result.papers[0].abstract,'');assert.equal(result.provider,'Crossref');
});
test('literature search reports provider errors and rejects invalid inputs',async()=>{
 await assert.rejects(searchLiterature({query:'x'}),/between/);
 await assert.rejects(searchLiterature({query:'methods'},async()=>({ok:false,status:429})),/HTTP 429/);
 await assert.rejects(searchLiterature({query:'methods'},async()=>({ok:true,json:async()=>({})})),/invalid response/);
});
test('DOI verification distinguishes registration, missing records and service failure',async()=>{
 const {verifyDOIs}=await import('./literature.mjs');
 const results=await verifyDOIs({dois:['10.1234/a','10.1234/b','10.1234/c']},async url=>url.endsWith('a')?{ok:true,json:async()=>({message:{DOI:'10.1234/a',title:['A']}})}:url.endsWith('b')?{ok:false,status:404}:{ok:false,status:503});
 assert.deepEqual(results.records.map(r=>r.status),['registered','not-found','unavailable']);
 await assert.rejects(verifyDOIs({dois:['https://evil.invalid']}),/valid DOI/);
});
