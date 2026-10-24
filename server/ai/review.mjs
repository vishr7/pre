import { structured_call } from './structured-call.mjs';
import { reviewPrompt, reviewSchema, venues } from './review-prompt.mjs';
export function findPaper({ files = [], cells = [] } = {}) {
  const tex = files.filter(f => typeof f?.path === 'string' && f.path.endsWith('.tex') && typeof f.content === 'string' && f.content.trim());
  const main = tex.find(f => f.path === 'paper/main.tex') || tex.find(f => f.content.includes('\\begin{document}'));
  if (main) return main.content;
  return cells.filter(c => c?.type === 'latex' && typeof c.source === 'string' && c.source.trim()).map(c => c.source).join('\n\n');
}
export function paperSections(latex) {
  const sections = [...latex.matchAll(/\\(?:sub)*section\*?\{([^}]*)\}/g)].map(match => match[1]);
  return latex.includes('\\begin{abstract}') ? ['Abstract', ...sections] : sections;
}
// Every comment must quote the paper verbatim so the editor can highlight it; unanchored comments are dropped.
export function validateReview(latex, review) {
  if (typeof review?.summary !== 'string' || !Array.isArray(review.comments) || !Array.isArray(review.action_items)) throw new Error('Expected a summary, comments, and action items.');
  const comments = review.comments.filter(c => typeof c?.quote === 'string' && c.quote.trim().length >= 4 && latex.includes(c.quote));
  if (review.comments.length && !comments.length) throw new Error('No comment quote appears verbatim in the paper.');
  const kept = new Set(comments.map(c => c.id));
  const action_items = review.action_items.map(a => ({ ...a, related_comment_ids: (a.related_comment_ids || []).filter(id => kept.has(id)) }));
  return { summary: review.summary, scores: review.scores, comments, action_items };
}
export async function reviewPaper({ files, cells, latex: suppliedLatex, venue = 'generic' } = {}, dependencies) {
  if(suppliedLatex !== undefined && typeof suppliedLatex !== 'string')throw new Error('Paper source must be text.');
  const latex = suppliedLatex ?? findPaper({ files, cells });
  if (!latex.trim()) throw new Error('No paper found. Add paper/main.tex or a LaTeX cell, then start the review.');
  if (latex.length > 200000) throw new Error('The paper exceeds the 200,000 character review limit.');
  return structured_call({ prompt: reviewPrompt(latex, venues[venue] ? venue : 'generic', paperSections(latex)), schema: reviewSchema, validate: review => validateReview(latex, review) }, dependencies);
}
