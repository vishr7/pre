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
import {fitWideTables} from '../src/paperFormat.ts';
test('ordinary tables are measured against column width, captions remain outside',()=>{
 const source=formatPaper(String.raw`\begin{table}\caption{Results}\begin{tabular}{lr}Name & Value\\\end{tabular}\end{table}`);
 const result=fitWideTables(source);
 assert.ok(result.includes(String.raw`\ifdim\wd0>\linewidth`));
 assert.ok(result.indexOf('Results')<result.indexOf(String.raw`\setbox0`));
 assert.equal(fitWideTables(result),result);
});
test('explicit sizing and verbatim examples are preserved',()=>{
 for(const source of [String.raw`\begin{table}\resizebox{\linewidth}{!}{\begin{tabular}{l}A\end{tabular}}\end{table}`,String.raw`\begin{verbatim}\begin{table}\begin{tabular}{l}A\end{tabular}\end{table}\end{verbatim}`])assert.equal(fitWideTables(source),source);
});
