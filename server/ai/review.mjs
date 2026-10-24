import { structured_call } from './structured-call.mjs';
import { reviewPrompt, reviewSchema, venues } from './review-prompt.mjs';
import { checkNumbers, arithmeticScore } from './number-check.mjs';
const severityOrder = { critical: 0, major: 1, minor: 2 };
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
  // The arithmetic audit is best-effort: if it fails, the review is still returned.
  const [review, audit] = await Promise.all([
    structured_call({ prompt: reviewPrompt(latex, venues[venue] ? venue : 'generic', paperSections(latex)), schema: reviewSchema, validate: review => validateReview(latex, review) }, dependencies),
    checkNumbers(latex, dependencies).catch(() => null),
  ]);
  return mergeNumberChecks(review, audit);
}
// Adds the code-computed arithmetic score (null if the audit failed or found nothing to check).
// Verified calculation errors replace reviewer comments on the same quote and get their own action item.
export function mergeNumberChecks(review, audit) {
  const numberComments = audit?.comments || [];
  review = { ...review, scores: { ...review.scores, arithmetic: audit ? arithmeticScore(audit) : null } };
  if (!numberComments.length) return review;
  const checked = new Set(numberComments.map(c => c.quote));
  const comments = [...review.comments.filter(c => !checked.has(c.quote)), ...numberComments].sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity]);
  const kept = new Set(comments.map(c => c.id));
  const action_items = review.action_items.map(a => ({ ...a, related_comment_ids: a.related_comment_ids.filter(id => kept.has(id)) }));
  action_items.push({ id: `a${action_items.length + 1}`, title: 'Correct calculation errors',
    description: `Recompute the ${numberComments.length} stated value(s) that do not match the paper's own numbers and update the text and tables.`,
    related_comment_ids: numberComments.map(c => c.id) });
  return { ...review, comments, action_items };
}
