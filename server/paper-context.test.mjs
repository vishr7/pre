import test from 'node:test';
import assert from 'node:assert/strict';
import { examinerSignedUrlPath, preparePaperContext, voiceSessionOptions } from '../src/paperContext.ts';

const cell = (source, filePath) => ({ id: 'paper-cell', type: 'latex', source, ...(filePath ? { filePath } : {}) });

test('loads a single paper and retains specific study details in readable context', () => {
  const detail = 'Our study uses a fictional dataset of 347 observations collected from three simulated university departments.';
  const context = preparePaperContext([{ path: 'main.tex', content: `\\documentclass{article}\n\\title{Study}\n\\begin{document}\n\\begin{abstract}We study outcomes.\\end{abstract}\n\\section{Methods}\n${detail}\n\\end{document}` }], []);
  assert.match(context, /Study/);
  assert.match(context, /Abstract/);
  assert.ok(context.includes(detail));
});

test('expands nested input and include references from the active project only', () => {
  const activeFiles = [
    { path: 'paper/main.tex', content: '\\documentclass{article}\n\\begin{document}\n\\input{sections/methods}\n\\end{document}' },
    { path: 'paper/sections/methods.tex', content: 'Methods detail. \\include{nested/results}' },
    { path: 'paper/sections/nested/results.tex', content: 'Result: 347 observations.' },
    { path: 'other/main.tex', content: 'SECRET FROM ANOTHER PROJECT' },
    { path: 'settings.json', content: 'API_KEY=not-for-context' },
  ];
  const context = preparePaperContext(activeFiles, []);
  assert.match(context, /Methods detail/);
  assert.match(context, /347 observations/);
  assert.doesNotMatch(context, /SECRET FROM ANOTHER PROJECT|not-for-context/);
});

test('gracefully marks missing and unsafe references without reading outside the project', () => {
  const context = preparePaperContext([{ path: 'main.tex', content: '\\documentclass{article}\n\\begin{document}\\input{missing} \\input{../../outside}\\end{document}' }], []);
  assert.match(context, /Missing LaTeX section: missing/);
  assert.match(context, /Skipped unsafe LaTeX reference/);
  assert.doesNotMatch(context, /outside secret/i);
});

test('returns empty for an empty project and supports notebook LaTeX cells', () => {
  assert.equal(preparePaperContext([], []), '');
  assert.match(preparePaperContext([], [cell('Notebook research detail: 347 observations.')]), /347 observations/);
});

test('bounds large paper context and notes that trailing content was omitted', () => {
  const long = `\\documentclass{article}\n\\begin{document}\n${'Research result. '.repeat(2000)}TAIL_MARKER\\end{document}`;
  const context = preparePaperContext([{ path: 'main.tex', content: long }], [], 1000);
  assert.ok(context.length <= 1000);
  assert.match(context, /remaining content omitted/);
  assert.doesNotMatch(context, /TAIL_MARKER/);
});

test('prioritizes methods, results, and conclusions in long papers', () => {
  const content = `\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\n${'Background context. '.repeat(1500)}\\section{Methods}\nDataset: 347 observations.\\section{Results}\nAccuracy was 0.87.\\section{Limitations}\nThree simulated departments limit generalization.\\section{Conclusion}\nFuture validation is needed.\\end{document}`;
  const context = preparePaperContext([{ path: 'main.tex', content }], [], 1200);
  assert.ok(context.length <= 1200);
  assert.match(context, /347 observations/);
  assert.match(context, /Accuracy was 0\.87/);
  assert.match(context, /Future validation is needed/);
  assert.match(context, /remaining content omitted/);
});

test('routes each examiner and puts the paper in SDK init without replacing the agent greeting', () => {
  const context = 'Dataset: fictional 347 observations.';
  for (const [examiner, expectedPath] of [['supportive', '/defend/signed-url?examiner=supportive'], ['critical', '/defend/signed-url?examiner=critical']]) {
    // The backend chooses the agent from the examiner query; the same active-paper
    // context is included in either SDK initialization after the signed URL returns.
    assert.equal(examinerSignedUrlPath(examiner), expectedPath);
    const options = voiceSessionOptions('signed-url-fixture', context);
    assert.equal(options.signedUrl, 'signed-url-fixture');
    assert.equal(options.dynamicVariables.paper_context, context);
    assert.equal(options.connectionType, 'websocket');
    assert.equal('overrides' in options, false);
  }
});
