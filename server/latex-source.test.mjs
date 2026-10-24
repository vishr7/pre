import test from 'node:test';
import assert from 'node:assert/strict';
import { notebookLatex } from '../src/latexSource.ts';
const latex = source => ({id:source,type:'latex',source});
test('combines LaTeX cells in order, ignoring code and empty cells',()=>{
 assert.equal(notebookLatex([latex('Title'),{type:'python',source:'print(1)'},latex(''),latex('Body')]),'Title\n\nBody');
 assert.equal(notebookLatex([latex('')]),undefined);
});
test('inserts fragments inside a complete document rather than after its end',()=>{
 const document='\\documentclass{article}\n\\begin{document}\nTitle\n\\end{document}';
 const combined=notebookLatex([latex(document),latex('Body')]);
 assert.ok(combined.indexOf('Body')<combined.indexOf('\\end{document}'));
 assert.equal(combined.match(/\\documentclass/g).length,1);
});
test('does not silently discard multiple documents or fragments after a broken document',()=>{
 assert.throws(()=>notebookLatex([latex('\\documentclass{article}'),latex('\\documentclass{book}')]),/end/);
 assert.throws(()=>notebookLatex([latex('\\documentclass{article}'),latex('Body')]),/end/);
});

import { paperLatex } from '../src/latexSource.ts';
test('paper combines files and inserts referenced files only once',()=>{
 const result=paperLatex([
 {path:'paper/main.tex',content:'\\documentclass{article}\n\\begin{document}\n\\input{sections/intro}\n\\end{document}'},
 {path:'paper/sections/intro.tex',content:'Introduction content'},
 {path:'paper/results.tex',content:'Results content'},
 {path:'notes.md',content:'Not in paper'},
 ]);
 assert.equal(result.match(/Introduction content/g).length,1);
 assert.ok(result.includes('Results content'));
 assert.ok(result.indexOf('Results content')<result.indexOf('\\end{document}'));
 assert.ok(!result.includes('Not in paper'));
});
test('paper handles fragment-only projects and rejects inclusion cycles',()=>{
 assert.equal(paperLatex([{path:'b.tex',content:'B'},{path:'a.tex',content:'A'}]),'A\n\nB');
 assert.throws(()=>paperLatex([{path:'a.tex',content:'\\input{b}'},{path:'b.tex',content:'\\input{a}'}]),/Circular/);
 assert.equal(paperLatex([]),'\\null');
});
test('paper includes notebook LaTeX cells in order alongside file content',()=>{
 const result=paperLatex([{path:'paper/main.tex',content:'\\documentclass{article}\n\\begin{document}\nFile text\n\\end{document}'}],[latex('Cell one'),{id:'code',type:'python',source:'print(42)'},latex('Cell two')]);
 assert.ok(result.includes('File text'));
 assert.ok(result.indexOf('Cell one')<result.indexOf('Cell two'));
 assert.ok(result.indexOf('Cell two')<result.indexOf('\\end{document}'));
 assert.ok(!result.includes('print(42)'));
});
test('a complete notebook document replaces the empty starter paper',()=>{
 const document='\\documentclass{article}\n\\begin{document}\nHomework 7\n\\end{document}';
 const result=paperLatex([{path:'paper/main.tex',content:'\\documentclass{article}\n\\begin{document}\n\\null\n% Write your paper here.\n\\end{document}'}],[latex(document)]);
 assert.equal(result,document);
});

test('paper combines complete files and cells with one wrapper and preserves sources', () => {
 const root = String.raw`\documentclass{article}
\usepackage{amsmath}
\begin{document}
Main body
\end{document}`;
 const secondary = String.raw`\documentclass{report}
\usepackage{amsmath}
\usepackage{amssymb}
\newcommand{\result}{Result}
\begin{document}
Secondary body \result
\end{document}`;
 const cells = [latex(secondary), latex('Final fragment')];
 const result = paperLatex([{path:'paper/main.tex',content:root}],cells);
 assert.equal(result.match(/\\documentclass/g).length,1);
 assert.equal(result.match(/\\begin\{document\}/g).length,1);
 assert.equal(result.match(/\\end\{document\}/g).length,1);
 assert.equal(result.match(/Secondary body/g).length,1);
 assert.equal(result.match(/\\usepackage\{amsmath\}/g).length,1);
 assert.ok(result.includes(String.raw`\newcommand{\result}{Result}`));
 assert.ok(result.indexOf(String.raw`\usepackage{amssymb}`)<result.indexOf(String.raw`\begin{document}`));
 assert.ok(result.indexOf('Final fragment')<result.indexOf(String.raw`\end{document}`));
 assert.equal(cells[0].source,secondary);
});
test('identical paper and notebook documents compile once',()=>{
 const source=String.raw`\documentclass{article}
\begin{document}
Shared manuscript
\end{document}`;
 const result=paperLatex([{path:'paper/main.tex',content:source}],[latex(source)]);
 assert.equal(result.match(/Shared manuscript/g).length,1);
});
test('notebook fragment mirrored inside a paper file is included once',()=>{
 const fragment='Shared section text';
 const source=String.raw`\documentclass{article}
\begin{document}
Shared section text
\end{document}`;
 const result=paperLatex([{path:'paper/main.tex',content:source}],[latex(fragment)]);
 assert.equal(result.match(/Shared section text/g).length,1);
});
