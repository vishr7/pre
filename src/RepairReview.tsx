import { DiffEditor } from '@monaco-editor/react';
import { Check, LoaderCircle, Sparkles, X } from 'lucide-react';
export type RepairProposal = { summary: string; edits: {old_text:string;new_text:string;reason:string}[]; source: string };
export type RepairState = {
  original: string; phase: 'generating' | 'checking' | 'ready' | 'failed';
  proposal?: RepairProposal; verified?: boolean; pdfUrl?: string; logs?: string; error?: string; filesSnapshot: string;
};
export default function RepairReview({ repair, disabled, onAccept, onReject, onRetry }: {
  repair: RepairState; disabled: boolean; onAccept: () => void; onReject: () => void; onRetry: () => void;
}) {
  const working = repair.phase === 'generating' || repair.phase === 'checking';
  return <div className="repair-review" aria-label="AI repair review">
    <div className="repair-title"><Sparkles size={14}/><strong>Suggested fix</strong><span className={`repair-badge ${repair.verified ? 'verified' : ''}`} role="status">{working && <LoaderCircle size={12} className="spin"/>}{repair.phase === 'generating' ? 'Finding a fix…' : repair.phase === 'checking' ? 'Checking compilation…' : repair.verified ? 'Compilation passed' : 'Not verified'}</span></div>
    <p className="repair-summary">{repair.proposal?.summary || (working ? 'Your original cell stays unchanged while the fix is prepared.' : repair.error)}</p>
    {repair.proposal && <><div className="repair-diff-labels"><span>Original</span><span>Proposed fix</span></div><DiffEditor height={Math.min(360, Math.max(160, Math.max(repair.original.split('\n').length,repair.proposal.source.split('\n').length)*20+30))} language="latex" theme="pearl" original={repair.original} modified={repair.proposal.source} options={{readOnly:true,originalEditable:false,renderSideBySide:true,useInlineViewWhenSpaceIsLimited:false,minimap:{enabled:false},fontSize:12,lineHeight:20,scrollBeyondLastLine:false,automaticLayout:true,wordWrap:'on',renderOverviewRuler:false}}/><ul className="repair-reasons">{repair.proposal.edits.map((edit,i)=><li key={i}>{edit.reason}</li>)}</ul></>}
    {repair.error && repair.proposal && <p className="repair-error" role="alert">{repair.error}</p>}
    {repair.logs && !repair.verified && <details className="repair-log"><summary>Compiler output</summary><pre>{repair.logs}</pre></details>}
    <div className="repair-actions"><span>{repair.verified ? 'Compilation checked; review the content before accepting.' : 'Original code has not been changed.'}</span>{repair.phase === 'failed' && <button className="outline-btn" disabled={disabled} onClick={onRetry}>Try again</button>}<button className="outline-btn" onClick={onReject}><X size={13}/> Reject</button><button className="primary-btn" disabled={!repair.verified || disabled} onClick={onAccept}><Check size={13}/> Accept fix</button></div>
  </div>;
}
