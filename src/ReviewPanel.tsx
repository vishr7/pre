import { paperLatex } from './latexSource';
import { useState } from 'react';
import { FileText, LoaderCircle, Sparkles, SquarePen } from 'lucide-react';
import { request, type Cell, type ProjectFile } from './api';
export type ReviewComment = { id: string; section: string; quote: string; category: string; severity: 'minor' | 'major' | 'critical'; comment: string; suggestion: string };
export type Review = { summary: string; scores: Record<'methodology' | 'novelty' | 'clarity' | 'reproducibility', number>;
  comments: ReviewComment[]; action_items: { id: string; title: string; description: string; related_comment_ids: string[] }[] };
const venues = [['generic', 'General'], ['neurips', 'NeurIPS'], ['acl', 'ACL'], ['journal', 'Journal']];
export default function ReviewPanel({ base, files, cells, review, onReview, onShowQuote, onError }: {
  base: string; files: ProjectFile[]; cells: Cell[]; review: Review | null; onReview: (review: Review) => void;
  onShowQuote: (quote: string) => void; onError: (message: string) => void;
}) {
  const [venue, setVenue] = useState('generic');
  const [working, setWorking] = useState(false);
  async function start() {
    setWorking(true);
    try { onReview(await request<Review>(base, '/api/review', { latex: paperLatex(files, cells), venue })); }
    catch (error) { onError((error as Error).message); }
    finally { setWorking(false); }
  }
  return <div className="tool-workspace review-workspace">
    <div className="tool-eyebrow"><SquarePen size={12}/> PRE REVIEW</div>
    <h2>Review</h2>
    <p>An AI reviewer reads your combined paper and checks methodology, evidence, novelty, reproducibility, and clarity. Every comment quotes your paper exactly.</p>
    <div className="review-controls">
      <select aria-label="Review venue" value={venue} disabled={working} onChange={e => setVenue(e.target.value)}>{venues.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <button className="primary-btn" disabled={working} onClick={start}>{working ? <LoaderCircle size={15} className="spin"/> : <Sparkles size={15}/>}{working ? 'Reviewing…' : review ? 'Review again' : 'Start review'}</button>
    </div>
    {review && <>
      <div className="review-section"><p className="review-summary">{review.summary}</p>
        <div className="review-scores">{Object.entries(review.scores).map(([name, value]) => <div key={name}><b>{value}<small>/5</small></b><span>{name}</span></div>)}</div></div>
      <div className="review-heading">Comments <span>{review.comments.length}</span></div>
      {review.comments.map(c => <article key={c.id} className={`review-comment ${c.severity}`}>
        <div className="review-tags"><strong>{c.id}</strong><span className={`review-badge ${c.severity}`}>{c.severity}</span><span>{c.category.replace('_', ' ')}</span><span>{c.section}</span>
          <button className="review-show" onClick={() => onShowQuote(c.quote)}><FileText size={12}/> Show in paper</button></div>
        <code className="review-quote">{c.quote}</code>
        <p>{c.comment}</p><p className="review-fix"><b>Fix:</b> {c.suggestion}</p>
      </article>)}
      <div className="review-heading">Action items <span>{review.action_items.length}</span></div>
      <ol className="review-actions">{review.action_items.map(a => <li key={a.id}><strong>{a.title}</strong><p>{a.description}</p>{a.related_comment_ids.length > 0 && <small>Addresses {a.related_comment_ids.join(', ')}</small>}</li>)}</ol>
    </>}
    <div className="context-note"><FileText size={16}/> Includes project LaTeX files and notebook LaTeX cells, just like Paper.</div>
  </div>;
}
