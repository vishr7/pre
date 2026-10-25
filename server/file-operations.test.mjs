import test from 'node:test';
import assert from 'node:assert/strict';
import {moveProjectFile,validProjectPath} from '../src/fileOperations.ts';
import {linkFiles} from '../src/projectSync.ts';
import {paperLatex} from '../src/latexSource.ts';
test('moving a section updates inputs, preserves cell identity and assembled content',()=>{
 const state=linkFiles([],[{path:'main.tex',content:String.raw`\documentclass{article}
\begin{document}
\input{sections/intro}
\end{document}`},{path:'sections/intro.tex',content:String.raw`\section{Introduction} Text.`}]);
 const before=paperLatex(state.files,state.cells);const id=state.cells.find(c=>c.filePath==='sections/intro.tex').id;
 const next=moveProjectFile(state,'sections/intro.tex','sections/background/intro.tex');
 assert.equal(next.cells.find(c=>c.filePath==='sections/background/intro.tex').id,id);
 assert.match(next.files[0].content,/sections\/background\/intro/);
 assert.equal(paperLatex(next.files,next.cells),before);
});
test('moving an includer preserves child references and does not rewrite comments',()=>{
 const state=linkFiles([],[{path:'main.tex',content:String.raw`\documentclass{article}\begin{document}\input{sections/methods}\end{document}`},{path:'sections/methods.tex',content:String.raw`\input{detail}
% \input{detail}`},{path:'sections/detail.tex',content:'Details.'}]);
 const next=moveProjectFile(state,'sections/methods.tex','methods.tex');
 assert.equal(next.files.find(f=>f.path==='methods.tex').content,String.raw`\input{sections/detail}
% \input{detail}`);
 assert.equal(paperLatex(next.files,next.cells).replace(/%[^\n]*/g,''),paperLatex(state.files,state.cells).replace(/%[^\n]*/g,''));
});
test('moves reject collisions and unsafe paths without changing the workspace',()=>{
 const state={cells:[],files:[{path:'a.tex',content:'A'},{path:'b.tex',content:'B'}]};
 assert.throws(()=>moveProjectFile(state,'a.tex','b.tex'),/already exists/);
 assert.throws(()=>moveProjectFile(state,'a.tex','b.tex/child.tex'),/folder/);
 for(const path of ['../x.tex','/x.tex','a//b.tex','a\\b.tex','a/%b.tex'])assert.throws(()=>validProjectPath(path));
 assert.equal(state.files[0].path,'a.tex');assert.equal(moveProjectFile(state,'a.tex','a.tex'),state);
});
test('bibliography moves update literal references without touching unrelated text',()=>{
 const state={cells:[],files:[{path:'main.tex',content:String.raw`\bibliography{refs} refs.bib`},{path:'refs.bib',content:'@article{a,title={Example}}'}]};
 assert.equal(moveProjectFile(state,'refs.bib','references/refs.bib').files[0].content,String.raw`\bibliography{references/refs} refs.bib`);
});
