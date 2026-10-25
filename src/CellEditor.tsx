import { useEffect, useRef, useState } from 'react';
import Editor, { type OnMount } from '@monaco-editor/react';
import type { Cell } from './api';

const MIN_HEIGHT = 44;
const MAX_HEIGHT = 1200;
const clamp = (height: number) => Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, Math.round(height)));

type Props = {
  cell: Cell;
  onGenerate: (source: string, line: number) => void;
  onChange: (source: string) => void;
  onMount?: OnMount;
  onContext?: (selection:string)=>void;
  onResize: (height: number | undefined) => void;
};

export default function CellEditor({ cell, onChange, onResize, onGenerate, onContext, onMount }: Props) {
  const [contentHeight, setContentHeight] = useState(() => Math.min(480, Math.max(MIN_HEIGHT, cell.source.split('\n').length * 20 + 24)));
  const [dragHeight, setDragHeight] = useState<number | null>(null);
  const drag = useRef<{ y: number; height: number; latest: number } | null>(null);
  const subscription = useRef<{ dispose: () => void } | null>(null);
  const latest = useRef({cell,onGenerate,onContext}); latest.current = {cell,onGenerate,onContext};
  const keySubscription = useRef<{dispose: () => void} | null>(null);
  const contextSubscriptions=useRef<{dispose:()=>void}[]>([]);
  const height = dragHeight ?? (cell.editorHeight === undefined ? contentHeight : clamp(cell.editorHeight));
  const mount: OnMount = (editor,monaco) => {
    const measure = () => setContentHeight(Math.min(480, Math.max(MIN_HEIGHT, editor.getContentHeight())));
    subscription.current?.dispose();
    subscription.current = editor.onDidContentSizeChange(measure);
    keySubscription.current?.dispose();
    keySubscription.current = editor.onKeyDown(event => {
      if(event.browserEvent.key !== 'Enter' || event.browserEvent.isComposing || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey || latest.current.cell.type !== 'latex')return;
      const position = editor.getPosition(); const model = editor.getModel();
      if(!position || !model || !editor.getSelection()?.isEmpty())return;
      if(!/^\s*pre\s+\S/i.test(model.getLineContent(position.lineNumber)))return;
      event.preventDefault(); event.stopPropagation();
      latest.current.onGenerate(model.getValue(),position.lineNumber);
    });
    contextSubscriptions.current.forEach(s=>s.dispose());
    const publish=()=>{const selection=editor.getSelection();latest.current.onContext?.(selection?editor.getModel()?.getValueInRange(selection).slice(0,12000)||'':'');};
    contextSubscriptions.current=[editor.onDidFocusEditorText(publish),editor.onDidChangeCursorSelection(()=>{if(editor.hasTextFocus())publish();})];
    measure();
    onMount?.(editor,monaco);
  };
  useEffect(() => () => { subscription.current?.dispose(); keySubscription.current?.dispose(); contextSubscriptions.current.forEach(s=>s.dispose()); }, []);
  return <div className="cell-editor">
    <Editor height={height} theme="pearl" language={cell.type} value={cell.source}
      onChange={value => onChange(value || '')} onMount={mount}
      options={{ minimap: { enabled: false }, fontSize: 12, lineHeight: 20, padding: { top: 12, bottom: 12 },
        scrollBeyondLastLine: false, wordWrap: 'on', automaticLayout: true, overviewRulerLanes: 0,
        scrollbar: { vertical: 'auto', horizontal: 'hidden', verticalScrollbarSize: 6, alwaysConsumeMouseWheel: false },
        lineNumbersMinChars: 3, folding: false, renderLineHighlight: 'none' }}/>
    <div className="cell-resize-bar">
      <div className="cell-resize-handle" role="separator" tabIndex={0} aria-label="Resize cell editor"
        aria-orientation="horizontal" aria-valuemin={MIN_HEIGHT} aria-valuemax={MAX_HEIGHT} aria-valuenow={height}
        aria-valuetext={`${height} pixels, ${cell.editorHeight === undefined ? 'automatic' : 'manual'} height`}
        title="Drag to resize. Double-click to fit content. Arrow keys resize; Enter restores automatic sizing."
        onPointerDown={event => { if(event.button !== 0)return; event.preventDefault();event.currentTarget.focus();event.currentTarget.setPointerCapture(event.pointerId);drag.current = {y:event.clientY,height,latest:height}; }}
        onPointerMove={event => {if(!drag.current)return;const next=clamp(drag.current.height + event.clientY - drag.current.y);drag.current.latest=next;setDragHeight(next);}}
        onPointerUp={event => {if(!drag.current)return;onResize(drag.current.latest);drag.current=null;setDragHeight(null);event.currentTarget.releasePointerCapture(event.pointerId);}}
        onPointerCancel={() => {drag.current=null;setDragHeight(null);}}
        onDoubleClick={() => onResize(undefined)}
        onKeyDown={event => {
          if(event.key === 'ArrowUp' || event.key === 'ArrowDown'){event.preventDefault();onResize(clamp(height + (event.key === 'ArrowUp' ? -20 : 20)));}
          if(event.key === 'Enter' || event.key === 'Home'){event.preventDefault();onResize(undefined);}
        }}><span/></div>
      {cell.editorHeight !== undefined && <button className="cell-fit" title="Restore automatic cell height" onClick={() => onResize(undefined)}>Fit content</button>}
    </div>
  </div>;
}
