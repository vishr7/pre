import test from 'node:test';
import assert from 'node:assert/strict';
import {composeImage} from './ai/image-compose.mjs';
test('sends image data to Gemini and validates targeted source edits',async()=>{
 const source='% Screenshot layout\n';
 const image={mimeType:'image/png',data:'aGVsbG8='};
 const result=await composeImage({source,instruction:'Make a centered title',image},{env:{GEMINI_API_KEY:'test',GEMINI_MODEL:'test'},fetchImpl:async(url,options)=>{
 const parts=JSON.parse(options.body).contents[0].parts;
 assert.deepEqual(parts[1].inlineData,image);
 return {ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify({summary:'Title',edits:[{old_text:source,new_text:'\\begin{center}Title\\end{center}',reason:'Match the screenshot'}]})}]}}]})};
 }});
 assert.ok(result.source.includes('Title'));
});
test('rejects unsupported and oversized attachments before calling Gemini',async()=>{
 for(const image of [{mimeType:'image/svg+xml',data:'abcd'},{mimeType:'image/png',data:'a'.repeat(2800001)}])await assert.rejects(composeImage({source:'test',instruction:'test',image}),/Attach/);
});
