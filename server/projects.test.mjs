import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
const compile = source => ts.transpile(source, {module:ts.ModuleKind.ESNext});
const dataUrl = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const paperFormat = dataUrl(compile(await readFile(new URL('../src/paperFormat.ts', import.meta.url), 'utf8')));
const starter = dataUrl(compile(await readFile(new URL('../src/starter.ts', import.meta.url), 'utf8')).replace("'./paperFormat'", JSON.stringify(paperFormat)));
const projectSource = compile(await readFile(new URL('../src/projects.ts', import.meta.url), 'utf8')).replace("'./starter'", JSON.stringify(starter));
const { newProject, readProjects, writeProjects, storedCells } = await import(dataUrl(projectSource));
const data = new Map();
Object.defineProperty(globalThis, 'localStorage', {value:{ getItem:key=>data.get(key)??null, setItem:(key,value)=>data.set(key,value) }, configurable:true});
test('New projects have independent blank cells and files and survive reload', () => {
 data.clear(); assert.deepEqual(readProjects(), []);
 const a = newProject('First project'); const b = newProject('Second project');
 assert.notEqual(a.id,b.id); const blank=b.cells[0].source;assert.equal(a.cells[0].type,'latex');assert.equal(a.cells[0].filePath,a.files[0].path);assert.equal(a.cells[0].source,a.files[0].content);
 a.cells[0].source = 'x = 42'; a.files[0].content = 'My paper';
 assert.equal(b.cells[0].source,blank); assert.notEqual(b.files[0].content,'My paper');
 writeProjects([a,b]); const reloaded=readProjects();
 assert.equal(reloaded[0].cells[0].source,'x = 42'); assert.equal(reloaded[1].cells[0].source,blank);
});
test('Existing work migrates once and remains unchanged', () => {
 data.clear(); const cell={id:'mine',type:'python',source:'print("keep my work")'};
 localStorage.setItem('pre.cells',JSON.stringify([cell]));
 localStorage.setItem('pre.files',JSON.stringify([{path:'notes.md',content:'Keep this'}]));
 const projects=readProjects(); assert.equal(projects.length,1); assert.deepEqual(projects[0].cells,[cell]);
 assert.equal(readProjects()[0].id,projects[0].id);
 assert.equal(readProjects()[0].files[0].content,'Keep this');
});
test('Archiving retains content and transient outputs are not persisted', () => {
 const p=newProject('Archived');p.archived=true;p.cells[0].source='42';writeProjects([p]);
 assert.equal(readProjects()[0].archived,true);assert.equal(readProjects()[0].cells[0].source,'42');
 const output=storedCells([{id:'x',type:'python',source:'42',status:'running',images:['large-image']}])[0];
 assert.equal(output.status,undefined);assert.equal(output.images,undefined);
});
