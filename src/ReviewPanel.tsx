import VenueMenu from './VenueMenu';
import { paperLatex } from './latexSource';
import { useState } from 'react';
import { FileText, LoaderCircle, Sparkles, SquarePen } from 'lucide-react';
import { request, type Cell, type ProjectFile } from './api';
import { prepareChatEdits, type ChatEdit, type EditProposal } from './chatEdits';
type Fix = { phase: 'working' | 'ready' | 'applied' | 'rejected'; message?: string; proposal?: EditProposal };
// The cell or .tex file whose source contains the quoted passage, for "Fix this".
function quoteTarget(quote: string, files: ProjectFile[], cells: Cell[]) {
  const file = files.find(f => f.path.endsWith('.tex') && f.content.includes(quote));
  if (file) return { target: 'file' as const, id: file.path, source: file.content };
  const cell = cells.find(c => c.type === 'latex' && c.source.includes(quote));
  return cell ? { target: 'cell' as const, id: cell.id, source: cell.source } : null;
}
export type ReviewComment = { id: string; section: string; quote: string; category: string; severity: 'minor' | 'major' | 'critical'; comment: string; suggestion: string };
export type Review = { summary: string; scores: Record<'methodology' | 'novelty' | 'clarity' | 'reproducibility', number> & { arithmetic?: number | null };
  comments: ReviewComment[]; action_items: { id: string; title: string; description: string; related_comment_ids: string[] }[] };
const reviewTypes: Record<string,string> = {
 generic: 'Start here for any paper. Checks whether your claims are supported, your methods are clear, and your results are explained.',
 neurips: 'For machine learning papers. Focuses on the contribution, comparisons with other methods, experiments, and reproducibility.',
 acl: 'For language and NLP papers. Focuses on datasets, comparisons, statistical evidence, limitations, and ethical considerations.',
 journal: 'For journal articles. Focuses on a complete account of the work, statistical rigor, related research, and well-supported conclusions.',
};
const scoreHelp: Record<string,string> = {methodology:'How sound and well explained your methods are.',novelty:'How clearly the paper establishes its contribution.',clarity:'How easy the paper is to follow.',reproducibility:'Whether others have enough detail to repeat the work.',arithmetic:'Whether the paper’s calculations and reported numbers add up. Checked by code, not estimated by AI.'};
export default function ReviewPanel({ base, files, cells, review, onReview, onShowQuote, onError, onApplyEdits }: {
  base: string; files: ProjectFile[]; cells: Cell[]; review: Review | null; onReview: (review: Review) => void;
  onShowQuote: (quote: string) => void; onError: (message: string) => void; onApplyEdits: (proposal: EditProposal, commentId: string) => Promise<boolean>;
}) {
  const [venue, setVenue] = useState('generic');
  const [working, setWorking] = useState(false);
  const [fixes, setFixes] = useState<Record<string, Fix>>({});
  const setFix = (id: string, fix: Fix) => setFixes(current => ({ ...current, [id]: fix }));
  async function start() {
    setWorking(true);
    try { onReview(await request<Review>(base, '/api/review', { latex: paperLatex(files, cells), venue })); setFixes({}); }
    catch (error) { onError((error as Error).message); }
    finally { setWorking(false); }
  }
  async function fix(comment: ReviewComment) {
    const target = quoteTarget(comment.quote, files, cells);
    if (!target) { onError('That passage is no longer in your paper. Run the review again.'); return; }
    setFix(comment.id, { phase: 'working' });
    try {
      const result = await request<{ message: string; edits: ChatEdit[] }>(base, '/api/review/fix', { comment, target });
      setFix(comment.id, { phase: 'ready', message: result.message, proposal: result.edits.length ? prepareChatEdits(result.edits, cells, files) : undefined });
    } catch (error) { setFixes(({ [comment.id]: _, ...rest }) => rest); onError((error as Error).message); }
  }
  async function apply(id: string, proposal: EditProposal) { if (await onApplyEdits(proposal, id)) setFix(id, { ...fixes[id], phase: 'applied' }); }
  return <div className="tool-workspace review-workspace">
    <div className="tool-eyebrow"><SquarePen size={12}/> PRE REVIEW</div>
    <h2>Get feedback on your paper</h2>
    <p className="review-intro">Find gaps in your argument, unclear explanations, and missing experimental details before you share your work.</p>
    <div className="review-source-note"><FileText size={17}/><div><strong>Reviews the document in Paper</strong><p>Includes your project’s LaTeX files and notebook LaTeX cells. Feedback is based on the written content; Review does not run your experiments.</p></div></div>
    <div className="review-setup"><h3>Choose a review focus</h3><p>Choose General if you’re unsure. The other options tailor the feedback to a type of publication.</p>
    <div className="review-controls">
      <VenueMenu value={venue} disabled={working} onChange={setVenue}/>
      <button className="primary-btn" disabled={working} onClick={start}>{working ? <LoaderCircle size={15} className="spin"/> : <Sparkles size={15}/>}{working ? 'Reviewing…' : review ? 'Review again' : 'Start review'}</button>
    </div>
    <p className="review-type-help" role="status">{working ? 'Reviewing your paper… usually 15–30 seconds. Checking claims, methods, and every calculation.' : reviewTypes[venue]}</p></div>
    {!review && <div className="review-explainer"><h3>What you’ll get</h3><div className="review-explainer-grid"><div><strong>Overall assessment</strong><p>A summary and scores for methods, contribution, clarity, and reproducibility.</p></div><div><strong>Comments on specific passages</strong><p>Each comment quotes your text, explains the issue, and suggests an improvement.</p></div><div><strong>Next steps</strong><p>Action items to help you decide what to revise. Your paper stays unchanged.</p></div></div></div>}
    {review && <>
      <div className="review-section"><p className="review-summary">{review.summary}</p>
        <p className="review-score-guide">AI assessment · 1 = needs substantial work, 5 = strong. These scores are guidance, not an acceptance prediction.</p><div className="review-scores">{Object.entries(review.scores).map(([name, value]) => <div key={name}><b>{value ?? '–'}{value != null && <small>/5</small>}</b><span>{name}</span><p className="review-score-help">{scoreHelp[name]}</p></div>)}</div></div>
      <p className="review-reading-guide">Start with critical issues, then major improvements and minor refinements. Select <b>Show in paper</b> to jump to the quoted passage.</p><div className="review-heading">Comments <span>{review.comments.length}</span></div>
      {review.comments.map(c => <article key={c.id} className={`review-comment ${c.severity}`}>
        <div className="review-tags"><strong>{c.id}</strong><span className={`review-badge ${c.severity}`}>{c.severity}</span><span>{c.category.replace('_', ' ')}</span><span>{c.section}</span>
          <button className="review-show" onClick={() => onShowQuote(c.quote)}><FileText size={12}/> Show in paper</button>
          <button className="review-show" disabled={!!fixes[c.id]} onClick={() => fix(c)}>{fixes[c.id]?.phase === 'working' ? <LoaderCircle size={12} className="spin"/> : <Sparkles size={12}/>} Fix this</button></div>
        <code className="review-quote">{c.quote}</code>
        <p>{c.comment}</p><p className="review-fix"><b>Fix:</b> {c.suggestion}</p>
        {fixes[c.id] && fixes[c.id].phase !== 'working' && <div className="chat-edit-proposal"><strong>Suggested fix</strong><p>{fixes[c.id].message}</p>
          {fixes[c.id].proposal?.edits.map((edit, j) => <details key={j} open><summary>{edit.target === 'cell' ? 'Notebook cell' : edit.id} · {edit.reason}</summary><pre className="chat-edit-old">− {edit.old_text}</pre><pre className="chat-edit-new">+ {edit.new_text}</pre></details>)}
          <div>{fixes[c.id].proposal && <button className="primary-btn" disabled={fixes[c.id].phase !== 'ready'} onClick={() => apply(c.id, fixes[c.id].proposal!)}>{fixes[c.id].phase === 'applied' ? 'Opened in paper' : 'Review in paper'}</button>}
            <button className="outline-btn" disabled={fixes[c.id].phase !== 'ready'} onClick={() => setFix(c.id, { ...fixes[c.id], phase: 'rejected' })}>{fixes[c.id].phase === 'rejected' ? 'Rejected' : fixes[c.id].proposal ? 'Reject' : 'Dismiss'}</button></div></div>}
      </article>)}
      <div className="review-heading">Action items <span>{review.action_items.length}</span></div>
      <ol className="review-actions">{review.action_items.map(a => <li key={a.id}><strong>{a.title}</strong><p>{a.description}</p>{a.related_comment_ids.length > 0 && <small>Addresses {a.related_comment_ids.join(', ')}</small>}</li>)}</ol>
    </>}
    <div className="context-note"><FileText size={16}/> Review suggests changes; you decide what to edit. Run it again after revising your paper.</div>
  </div>;
}
