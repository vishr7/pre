import test from 'node:test';
import assert from 'node:assert/strict';
import {arxivPdfUrl,fetchArxiv,planReplication} from './ai/paper-replication.mjs';
test('arXiv links normalize without permitting arbitrary network destinations',()=>{
 assert.equal(arxivPdfUrl('https://arxiv.org/abs/1706.03762'),'https://arxiv.org/pdf/1706.03762');
 assert.equal(arxivPdfUrl('https://arxiv.org/pdf/1706.03762v2.pdf'),'https://arxiv.org/pdf/1706.03762v2');
 for(const url of ['https://localhost/abs/1706.03762','https://arxiv.org.evil.com/abs/1706.03762','http://arxiv.org/abs/1706.03762','https://arxiv.org:444/abs/1706.03762','https://arxiv.org/abs/../../private'])assert.throws(()=>arxivPdfUrl(url));
});
test('paper fetch requires PDF bytes and refuses redirects',async()=>{
 const result=await fetchArxiv('https://arxiv.org/abs/1706.03762',async(url,options)=>{assert.equal(options.redirect,'error');return {ok:true,body:[Buffer.from('%PDF-1.7\nfixture')]};});
 assert.equal(Buffer.from(result.data,'base64').toString(),'%PDF-1.7\nfixture');
 await assert.rejects(fetchArxiv('https://arxiv.org/abs/1706.03762',async()=>({ok:true,body:[Buffer.from('<html>Error</html>')]})),/did not return a PDF/);
});
test('paper generation returns a plan and standalone source without executing it',async()=>{
 const plan={title:'Paper',summary:'Summary',experiment:'Statistics',methodology:'Section 2',steps:['Compute a mean'],requirements:['numpy'],missing:['Original dataset'],limitations:['Needs real data'],code:'print("test")',expected_results:'Not reported'};
 const result=await planReplication({text:'Paper method and results. '.repeat(10)},{env:{GEMINI_API_KEY:'test',GEMINI_MODEL:'test'},fetchImpl:async()=>({ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify(plan)}]}}]})})});
 assert.deepEqual(result,plan);
 await assert.rejects(planReplication({text:'short'}),/readable paper/);
});
