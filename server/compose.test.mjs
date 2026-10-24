import test from 'node:test';
import assert from 'node:assert/strict';
import { composeLatex } from './ai/compose.mjs';
const mock = latex => ({env:{GEMINI_API_KEY:'test',GEMINI_MODEL:'test'},fetchImpl:async()=>({ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify({latex})}]}}]})})});
test('replaces only the requested PRE line and preserves surrounding LaTeX',async()=>{
  const command='pre write a centered title saying HW 7 - 432';
  const latex='\\begin{center}\n{\\Large\\bfseries HW 7 - 432}\n\\end{center}';
  const result=await composeLatex({source:`\\section{Homework}\n${command}\nKeep this.\n${command}`,line:2},mock(latex));
  assert.equal(result.source,`\\section{Homework}\n${latex}\nKeep this.\n${command}`);
  assert.equal(result.edits[0].old_text,command);
});
test('requires a real PRE command at a valid line',async()=>{
  for(const line of [0,2,1.5])await assert.rejects(composeLatex({source:'pre title',line},mock('Title')));
  await assert.rejects(composeLatex({source:'\\section{Title}',line:1},mock('Title')));
});
test('rejects empty, fenced, and executable generated output',async()=>{
  for(const latex of ['', '```latex\nhello\n```', '\\write18{whoami}'])await assert.rejects(composeLatex({source:'pre make a title',line:1},mock(latex)));
});
