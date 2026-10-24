import test from 'node:test';
import assert from 'node:assert/strict';
import {figureAssets,compileErrorSummary} from '../src/figureAssets.ts';
test('saved replication figures have deterministic compiler paths',()=>{
 const assets=figureAssets([],[{path:'replication/experiment-123.results.json',content:JSON.stringify({images:['data:image/png;base64,aGVsbG8=']})}]);
 assert.deepEqual(assets,[{path:'figures/experiment-123-1.png',data:'aGVsbG8='}]);
});
test('missing graphics errors are concise and preserve the missing filename',()=>{
 const summary=compileErrorSummary("note: Running TeX ...\nerror: cell.tex:93: Unable to load picture or PDF file 'optimization_comparison.png'\n"+'log '.repeat(1000));
 assert.ok(summary.includes('optimization_comparison.png'));assert.ok(summary.includes('not applied'));assert.ok(summary.length<260);
});
