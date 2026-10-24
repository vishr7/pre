import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { DiffEditor } from '@monaco-editor/react';
import { Check, LoaderCircle, Sparkles, X } from 'lucide-react';
export type RepairProposal = { summary: string; edits: {old_text:string;new_text:string;reason:string}[]; source: string };
export type RepairState = {
  cellsSnapshot?: string; commandLine?: number; original: string; phase: 'generating' | 'checking' | 'ready' | 'failed';
  proposal?: RepairProposal; verified?: boolean; pdfUrl?: string; logs?: string; error?: string; filesSnapshot: string;
};
export default function RepairReview({ repair, disabled, onAccept, onReject, onRetry }: {
  repair: RepairState; disabled: boolean; onAccept: () => void; onReject: () => void; onRetry: () => void;
}) {
  const [actionHost, setActionHost] = useState<HTMLDivElement | null>(null);
  const diffSubscription = useRef<{ dispose: () => void } | null>(null);
  useEffect(() => () => diffSubscription.current?.dispose(), []);
  const actions = <><button className="outline-btn" onClick={onReject}><X size={13}/> Reject</button><button className="primary-btn" disabled={!repair.verified || disabled} onClick={onAccept} title="Accept all changes in this suggestion"><Check size={13}/> {repair.commandLine ? 'Accept' : 'Accept fix'}</button></>;
  const working = repair.phase === 'generating' || repair.phase === 'checking';
  return <div className="repair-review" aria-label="AI repair review">
    <div className="repair-title"><Sparkles size={14}/><strong>{repair.commandLine ? 'Generated LaTeX' : 'Suggested fix'}</strong><span className={`repair-badge ${repair.verified ? 'verified' : ''}`} role="status">{working && <LoaderCircle size={12} className="spin"/>}{repair.phase === 'generating' ? (repair.commandLine ? 'Writing LaTeX…' : 'Finding a fix…') : repair.phase === 'checking' ? 'Checking compilation…' : repair.verified ? 'Compilation passed' : 'Not verified'}</span></div>
    <p className="repair-summary">{repair.proposal?.summary || (working ? 'Your original cell stays unchanged while the fix is prepared.' : repair.error)}</p>
    {repair.proposal && <><div className="repair-inline-legend"><span className="added">+ Added</span><span className="removed">− Removed</span></div><DiffEditor key={repair.proposal.source} onMount={editor => {
      const modified = editor.getModifiedEditor();
      let zone: string | undefined;
      let anchoredLine: number | undefined;
      const host = document.createElement('div');
      host.className = 'repair-line-actions';
      setActionHost(host);
      const revealChange = () => {
        const change = editor.getLineChanges()?.[0];
        if (!change) return;
        const line = Math.max(1, change.modifiedStartLineNumber || change.modifiedEndLineNumber || 1);
        if (anchoredLine === line) return;
        anchoredLine = line;
        modified.changeViewZones(accessor => {
          if (zone) accessor.removeZone(zone);
          zone = accessor.addZone({afterLineNumber: line, heightInPx: 40, domNode: host, suppressMouseDown: false});
        });
        modified.revealLineInCenter(line);
      };
      diffSubscription.current?.dispose();
      const subscription = editor.onDidUpdateDiff(revealChange);
      diffSubscription.current = {dispose: () => { subscription.dispose(); }};
      revealChange();
    }} height={Math.min(360, Math.max(160, Math.max(repair.original.split('\n').length,repair.proposal.source.split('\n').length)*20+30))} language="latex" theme="pearl" original={repair.original} modified={repair.proposal.source} options={{readOnly:true,originalEditable:false,renderSideBySide:false,renderIndicators:true,renderMarginRevertIcon:false,minimap:{enabled:false},fontSize:12,lineHeight:20,scrollBeyondLastLine:true,automaticLayout:true,wordWrap:'on',renderOverviewRuler:false}}/><ul className="repair-reasons">{repair.proposal.edits.map((edit,i)=><li key={i}>{edit.reason}</li>)}</ul></>}
    {repair.proposal && actionHost && createPortal(actions, actionHost)}
    {repair.error && repair.proposal && <p className="repair-error" role="alert">{repair.error}</p>}
    {repair.logs && !repair.verified && <details className="repair-log"><summary>Compiler output</summary><pre>{repair.logs}</pre></details>}
    <div className="repair-actions"><span>{repair.verified ? 'Compilation checked; review the content before accepting.' : 'Original code has not been changed.'}</span>{repair.phase === 'failed' && <button className="outline-btn" disabled={disabled} onClick={onRetry}>Try again</button>}{!repair.proposal && actions}</div>
  </div>;
}
