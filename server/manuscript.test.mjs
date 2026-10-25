import test from 'node:test';
import assert from 'node:assert/strict';
import {organizeManuscript,addSection,sectionOffsets} from '../src/manuscript.ts';
import {paperLatex} from '../src/latexSource.ts';
const source=String.raw`\documentclass{article}
\begin{document}
\title{My work}
\section{Introduction}
A claim.
\section{Methods}
\begin{figure}Figure content.\end{figure}
\end{document}`;
test('organization preserves assembled content, code, assets and a complete recovery snapshot',()=>{
 const state={files:[{path:'paper/main.tex',content:source},{path:'src/trial.py',content:'print(1)'}],cells:[{id:'code',type:'python',source:'print(2)'}]};
 const next=organizeManuscript(state);
 assert.ok(next.files.some(f=>f.path==='main.tex'));assert.equal(next.files.filter(f=>f.path.startsWith('sections/')).length,2);
 assert.equal(paperLatex(next.files,next.cells).replace(/\s+/g,''),source.replace(/\s+/g,''));
 assert.deepEqual(JSON.parse(next.files.find(f=>f.path.startsWith('history/')).content),state);
 assert.ok(next.cells.some(c=>c.id==='code'));assert.ok(next.files.some(f=>f.path==='src/trial.py'));
});
test('adding a section links a unique file to a legacy nested root',()=>{
 const state={files:[{path:'paper/main.tex',content:source}],cells:[]};
 const next=addSection(addSection(state));
 assert.ok(next.files[0].content.includes('\\input{../sections/new-section.tex}'));
 assert.ok(next.files.some(f=>f.path==='sections/new-section-2.tex'));
 assert.equal((paperLatex(next.files,next.cells).match(/\\section\{New section\}/g)||[]).length,2);
});
test('organization ignores headings in comments, macros and environments',()=>{
 assert.equal(sectionOffsets(String.raw`% \section{Comment}
\newcommand{\x}{\section{Macro}}
\begin{figure}\section{Inside figure}\end{figure}
\section{Real} Text`).length,1);
 assert.throws(()=>organizeManuscript({files:[{path:'main.tex',content:'No headings'}],cells:[]}),/heading/);
});
