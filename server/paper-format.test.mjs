import test from 'node:test';
import assert from 'node:assert/strict';
import {formatPaper,blankPaper} from '../src/paperFormat.ts';
test('fragments and new projects share academic layout defaults',()=>{
 const result=formatPaper('\\section{Introduction}\nText');
 assert.ok(result.includes('11pt,letterpaper'));assert.ok(result.includes('[margin=1in]{geometry}'));
 assert.ok(result.includes('\\section{Introduction}'));assert.ok(blankPaper.includes('[margin=1in]'));
 assert.equal(result.match(/\\begin\{document\}/g).length,1);
});
test('custom document templates are preserved exactly',()=>{
 const custom='\\documentclass[twocolumn]{article}\n\\begin{document}\nCustom\n\\end{document}';
 assert.equal(formatPaper(custom),custom);
});
