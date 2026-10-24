import { structured_call } from './structured-call.mjs';
import { composePrompt, composeSchema } from './compose-prompt.mjs';
import { validateRepair } from './repair.mjs';
export async function composeLatex({ source, line }, dependencies) {
  if (typeof source !== 'string' || source.length > 200000 || !Number.isInteger(line)) throw new Error('Provide a LaTeX cell and command line.');
  const lines = source.split('\n');
  const command = lines[line - 1];
  const match = command?.match(/^\s*pre\s+(.+?)\s*$/i);
  if (!match) throw new Error('Write pre followed by an instruction on its own line.');
  return structured_call({ prompt: composePrompt(source, match[1], line), schema: composeSchema, validate: result => {
    if (typeof result?.latex !== 'string' || !result.latex.trim() || result.latex.includes('```')) throw new Error('Expected nonempty LaTeX without Markdown fences.');
    const proposal = validateRepair(command, { summary: 'Generated LaTeX from your instruction.', edits: [{ old_text: command, new_text: result.latex, reason: match[1] }] });
    const modified = [...lines]; modified[line - 1] = proposal.source;
    const combined = modified.join('\n');
    if (combined.length > 200000) throw new Error('Generated cell exceeds the size limit.');
    return { ...proposal, source: combined };
  } }, dependencies);
}
