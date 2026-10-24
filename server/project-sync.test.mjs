import test from 'node:test';
import assert from 'node:assert/strict';
import {linkFiles,changeCells} from '../src/projectSync.ts';
import {paperLatex} from '../src/latexSource.ts';
test('file and notebook edits share a stable identity after text diverges',()=>{
 let state=linkFiles([{id:'python',type:'python',source:'print(1)'}],[{path:'paper/main.tex',content:'Original'}]);
 const linked=state.cells.find(c=>c.filePath);const id=linked.id;
 state=changeCells(state,state.cells.map(c=>c.id===id?{...c,source:'Completely new text'}:c));
 assert.equal(state.files[0].content,'Completely new text');
 state=linkFiles(state.cells,[{...state.files[0],content:'File edit'}]);
 assert.equal(state.cells.find(c=>c.id===id).source,'File edit');
 assert.equal(paperLatex(state.files,state.cells),'File edit');
 assert.equal(state.cells[0].source,'print(1)');
});
test('reload preserves links, adopts identical legacy cells, preserves distinct content',()=>{
 const state=linkFiles([{id:'same',type:'latex',source:'Text'},{id:'unique',type:'latex',source:'Unique'}],[{path:'a.tex',content:'Text'}]);
 assert.equal(state.cells.length,2);assert.equal(state.cells[0].filePath,'a.tex');
 assert.deepEqual(linkFiles(state.cells,state.files),state);
 assert.ok(paperLatex(state.files,state.cells).includes('Unique'));
});
test('deleting either linked representation removes its counterpart',()=>{
 const state=linkFiles([],[{path:'a.tex',content:'Text'}]);
 assert.equal(changeCells(state,[]).files.length,0);
 assert.equal(linkFiles(state.cells,[]).cells.length,0);
});

import {editPaper} from '../src/projectSync.ts';
test('editing Paper updates the corresponding file-backed cell',()=>{
 const state=linkFiles([],[{path:'paper/main.tex',content:'Original paragraph'}]);
 const next=editPaper(state,paperLatex(state.files,state.cells),'Edited paragraph',paperLatex);
 assert.equal(next.files[0].content,'Edited paragraph');assert.equal(next.cells[0].source,'Edited paragraph');
 assert.equal(next.files.length,1);
});
test('editing a standalone notebook fragment in Paper preserves separate cells',()=>{
 const state=linkFiles([{id:'a',type:'latex',source:'First paragraph'},{id:'b',type:'latex',source:'Second paragraph'}],[]);
 const next=editPaper(state,paperLatex([],state.cells),'First paragraph\n\nRevised paragraph',paperLatex);
 assert.equal(next.cells[1].source,'Revised paragraph');assert.equal(next.cells.length,2);
});
test('cross-source edits remain identical in both views and retain recovery data',()=>{
 const state=linkFiles([{id:'a',type:'latex',source:'First paragraph'},{id:'code',type:'python',source:'print(1)'},{id:'b',type:'latex',source:'Second paragraph'}],[]);
 const next=editPaper(state,paperLatex([],state.cells),'One merged paragraph',paperLatex);
 assert.equal(paperLatex(next.files,next.cells),'One merged paragraph');
 assert.ok(next.cells.some(c=>c.type==='python'&&c.source==='print(1)'));
 assert.ok(next.files.some(f=>f.path.startsWith('history/')&&f.content.includes('Second paragraph')));
 const updated=changeCells(next,next.cells.map(c=>c.type==='latex'?{...c,source:'Notebook edit'}:c));
 assert.equal(paperLatex(updated.files,updated.cells),'Notebook edit');
});
