import { structured_call } from './structured-call.mjs';
import { repairPrompt, repairSchema } from './repair-prompt.mjs';
export function validateRepair(source, proposal) {
  if (typeof proposal?.summary !== 'string' || proposal.summary.length > 3000 || !Array.isArray(proposal.edits) || proposal.edits.length > 12) throw new Error('Expected a summary and at most 12 targeted edits.');
  const ranges = proposal.edits.map(edit => {
    if (![edit.old_text, edit.new_text, edit.reason].every(value => typeof value === 'string') || !edit.old_text || !edit.reason.trim()) throw new Error('Each edit needs a nonempty exact source quote and explanation.');
    const start = source.indexOf(edit.old_text);
    if (start < 0 || source.indexOf(edit.old_text, start + 1) !== -1) throw new Error('Each old_text must occur exactly once in the source.');
    if (edit.old_text === edit.new_text) throw new Error('Edits must change the source.');
    if (source.length > 300 && edit.old_text.length > source.length * 0.8) throw new Error('Use a targeted edit rather than replacing the whole document.');
    return { ...edit, start, end: start + edit.old_text.length };
  }).sort((a,b)=>a.start-b.start);
  for(let i=1;i<ranges.length;i++)if(ranges[i].start<ranges[i-1].end)throw new Error('Edits cannot overlap.');
  let modified = source;
  for(const edit of [...ranges].reverse())modified=modified.slice(0,edit.start)+edit.new_text+modified.slice(edit.end);
  if(modified.length>200000)throw new Error('Repaired cell exceeds the size limit.');
  // The compiler also runs in untrusted mode; reject newly introduced executable TeX primitives.
  const unsafe = /\\(?:write18|ShellEscape|input\s*\|)/g;
  if((modified.match(unsafe)||[]).length>(source.match(unsafe)||[]).length)throw new Error('Repair introduced an unsafe TeX command.');
  return { summary:proposal.summary, edits:ranges.map(({start,end,...edit})=>edit), source:modified };
}
export async function proposeLatexRepair({source,error}, dependencies) {
  if(typeof source!=='string'||!source.trim()||source.length>200000||typeof error!=='string')throw new Error('Provide the failed LaTeX source and compiler error.');
  return structured_call({prompt:repairPrompt(source,error),schema:repairSchema,validate:proposal=>validateRepair(source,proposal)},dependencies);
}
