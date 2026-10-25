import { test } from 'node:test';
import assert from 'node:assert/strict';
import { figureAssetBytes } from './runtime.mjs';
const png = Buffer.from('89504e470d0a1a0a0000', 'hex').toString('base64');
const pdf = Buffer.from('%PDF-1.5 test').toString('base64');
const jpg = Buffer.from('ffd8ffe000104a46', 'hex').toString('base64');
test('Uploaded PNG, JPG, and PDF figures keep their folder paths',()=>{
 assert.equal(figureAssetBytes({path:'nonlinearity-plot.pdf',data:pdf}).toString().slice(0,4),'%PDF');
 assert.ok(figureAssetBytes({path:'figures/results/plot_1.png',data:png}).length);
 assert.ok(figureAssetBytes({path:'img/photo.JPG',data:jpg}).length);
});
test('Figures with unsafe paths, wrong types, or fake contents are rejected',()=>{
 assert.throws(()=>figureAssetBytes({path:'../escape.png',data:png}),/Invalid/);
 assert.throws(()=>figureAssetBytes({path:'/etc/x.png',data:png}),/Invalid/);
 assert.throws(()=>figureAssetBytes({path:'.hidden/x.png',data:png}),/Invalid/);
 assert.throws(()=>figureAssetBytes({path:'script.sh',data:png}),/Invalid/);
 assert.throws(()=>figureAssetBytes({path:'fake.pdf',data:png}),/not a valid PDF/);
 assert.throws(()=>figureAssetBytes({path:'big.png',data:'A'.repeat(4000004)}),/Invalid/);
});
