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
 assert.throws(()=>notebookLatex([latex('\\documentclass{article}'),latex('\\documentclass{book}')]),/only one/);
 assert.throws(()=>notebookLatex([latex('\\documentclass{article}'),latex('Body')]),/end/);
});
