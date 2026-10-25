import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { organizePaperFolder, addFiguresPath, describeFile } from '../src/arxivImport.ts';
import { exposeSupportFiles } from './runtime.mjs';
const doc = body => `\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n${body}\n\\end{document}`;
const png = { data: 'iVBORw0KGgo=' };

test('An arXiv folder is sorted into main.tex, sections, figures, bibliography, and styles',()=>{
 const texts=[{path:'paper.tex',content:doc('\\input{intro}\n\\include{chapters/method.tex}\n\\bibliography{refs}')},
  {path:'intro.tex',content:'Intro \\input{chapters/method}'},{path:'chapters/method.tex',content:'Method'},
  {path:'refs.bib',content:'@a{}'},{path:'main.bbl',content:'\\begin{thebibliography}'},{path:'plain.bst',content:''},
  {path:'conf.sty',content:''},{path:'llncs.cls',content:''},{path:'README.md',content:'hi'}];
 const {files,figures,main}=organizePaperFolder(texts,[{path:'plot.pdf',...png},{path:'figures/a.png',...png},{path:'img/b.png',...png}]);
 assert.equal(main,'paper.tex');
 assert.deepEqual(files.map(f=>f.path).sort(),['README.md','bibliography/main.bbl','bibliography/plain.bst','bibliography/refs.bib','main.tex','sections/chapters/method.tex','sections/intro.tex','styles/conf.sty','styles/llncs.cls']);
 assert.deepEqual(figures.map(f=>f.path),['figures/plot.pdf','figures/a.png','figures/img/b.png']);
 const paper=files.find(f=>f.path==='main.tex').content;
 assert.match(paper,/\\input\{sections\/intro\}/);assert.match(paper,/\\include\{sections\/chapters\/method\.tex\}/);
 assert.match(paper,/\\bibliography\{refs\}/); // bibliography names are untouched; compile finds them
 assert.match(paper,/\\graphicspath\{\{figures\/\}\}\n\\begin\{document\}/);
 assert.match(files.find(f=>f.path==='sections/intro.tex').content,/\\input\{sections\/chapters\/method\}/);
});

test('The main document is chosen by name, otherwise the first complete document',()=>{
 assert.equal(organizePaperFolder([{path:'appendix.tex',content:doc('A')},{path:'ms.tex',content:doc('B')}],[]).main,'ms.tex');
 assert.equal(organizePaperFolder([{path:'z.tex',content:doc('A')}],[],'paper/main.tex').files[0].path,'paper/main.tex');
 assert.equal(organizePaperFolder([{path:'notes.tex',content:'no document'}],[]).main,undefined);
});

test('Existing \\graphicspath folders are kept and moved under figures/',()=>{
 assert.equal(addFiguresPath('\\usepackage{graphicx}\\graphicspath{{img/}{./plots/}}'),'\\usepackage{graphicx}\\graphicspath{{figures/img/}{figures/plots/}{figures/}{img/}{./plots/}}');
 assert.equal(addFiguresPath('\\documentclass{article}\\begin{document}x'),'\\documentclass{article}\\begin{document}x'); // no graphicx: unchanged
});

test('Hovering explains each kind of paper file',()=>{
 assert.match(describeFile('main.tex'),/Main paper/);assert.match(describeFile('sections/intro.tex'),/section/);
 assert.match(describeFile('bibliography/refs.bib'),/Reference database/);assert.match(describeFile('x.bst'),/Reference style/);
 assert.match(describeFile('main.bbl'),/Pre-built reference list/);assert.match(describeFile('styles/conf.sty'),/Style package/);
 assert.match(describeFile('figures/a.PDF'),/Figure/);assert.equal(describeFile('notes.txt'),undefined);
});

test('Compile finds styles and bibliography files, preferring a pre-built .bbl over rebuilding from .bib',async()=>{
 const dir=await mkdtemp(path.join(tmpdir(),'pre-support-'));
 try{
  await exposeSupportFiles(dir,[{path:'styles/conf.sty',content:'STY'},{path:'bibliography/refs.bib',content:'BIB'},{path:'bibliography/main.bbl',content:'BBL'},{path:'sections/intro.tex',content:'x'}],'cell');
  assert.equal(await readFile(path.join(dir,'conf.sty'),'utf8'),'STY');
  assert.equal(await readFile(path.join(dir,'cell.bbl'),'utf8'),'BBL');
  assert.equal(existsSync(path.join(dir,'refs.bib')),false);assert.equal(existsSync(path.join(dir,'intro.tex')),false);
  const dir2=await mkdtemp(path.join(tmpdir(),'pre-support-'));
  await exposeSupportFiles(dir2,[{path:'bibliography/refs.bib',content:'BIB'}],'cell');
  assert.equal(await readFile(path.join(dir2,'refs.bib'),'utf8'),'BIB'); // no .bbl: references are built from .bib
  await rm(dir2,{recursive:true,force:true});
 }finally{await rm(dir,{recursive:true,force:true});}
});
