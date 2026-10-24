import { assistantContext } from './assistantContext';
import ReplicatePanel from './ReplicatePanel';
import ToolsMenu from './ToolsMenu';
import ImageCompose, { type ImageInstruction } from './ImageCompose';
import { notebookLatex, paperLatex } from './latexSource';
import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import Editor, { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import ReactMarkdown from 'react-markdown';
import { BookOpen, FileText, FlaskConical, Copy, ShieldCheck, Sparkles, Plus, ChevronDown, ChevronRight, Folder, Play, MoreHorizontal, Upload, Settings, PanelLeft, Download, Maximize2, Send, X, Check, Code2, ArrowUpRight, Search, RefreshCw, Trash2, SquarePen, GitBranch, CircleHelp, MessageSquare, Table2, Image, PanelRight, RotateCcw } from 'lucide-react';
import { request, type Cell, type ExecutionResult, type ProjectFile } from './api';
import './style.css';
import PdfPreview from './PdfPreview';
import CellEditor from './CellEditor';
import TerminalPanel from './TerminalPanel';
import RepairReview, { type RepairState, type RepairProposal } from './RepairReview';
import ReviewPanel, { type Review } from './ReviewPanel';
import ProjectApp from './ProjectApp';
import type { Project } from './projects';
(self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });
monaco.languages.register({ id: 'latex' });
monaco.languages.setMonarchTokensProvider('latex', { tokenizer: { root: [[/\\[a-zA-Z]+/, 'keyword'], [/%.*$/, 'comment'], [/[{}\[\]]/, 'delimiter'], [/\$[^$]*\$/, 'string']] } });
monaco.editor.defineTheme('pearl', { base: 'vs', inherit: true, rules: [{ token: 'keyword', foreground: 'A35283' }, { token: 'comment', foreground: '8B9A8C' }], colors: { 'editor.background': '#FFFFFF', 'editorLineNumber.foreground': '#C6C1C6', 'editor.lineHighlightBackground': '#FCF9FA', 'diffEditor.insertedLineBackground': '#e6f3e8', 'diffEditor.removedLineBackground': '#fbe7e9', 'diffEditor.insertedTextBackground': '#b9dfc480', 'diffEditor.removedTextBackground': '#efb6be80' } });
const modes = [{ name: 'Notebook', icon: BookOpen }, { name: 'Paper', icon: FileText }, { name: 'Review', icon: SquarePen }, { name: 'Experiment', icon: FlaskConical }, { name: 'Replicate', icon: Copy }, { name: 'Iterate', icon: RefreshCw }, { name: 'Defend', icon: ShieldCheck }];
function saved<T>(key: string, fallback: T): T { try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback; } catch { return fallback; } }
function App({ project, onHome, onSave }: { project: Project; onHome: () => void; onSave: (id: string, cells: Cell[], files: ProjectFile[]) => void }) {
 const [cells, setCells] = useState<Cell[]>(() => structuredClone(project.cells));
 const [files, setFiles] = useState<ProjectFile[]>(() => structuredClone(project.files));
 const [showPreview, setShowPreview] = useState(true); const [mode, setMode] = useState('Notebook'); const [selected, setSelected] = useState<string | null>(null);
 const [base, setBase] = useState(() => saved('pre.api', '')); const [settings, showSettings] = useState(false);
 const [notice, setNotice] = useState(''); const [busy, setBusy] = useState<string | null>(null); const [pdf, setPdf] = useState('');
 const [compileError, setCompileError] = useState('');
 const [previewTab, setPreviewTab] = useState('Preview'); const [zoom, setZoom] = useState(100); const [logs, setLogs] = useState('No compilation yet.');
 const [query, setQuery] = useState(''); const [message, setMessage] = useState(''); const [messages, setMessages] = useState<{role: string; text: string; cells?: {language: Cell['type']; source: string}[]; inserted?: boolean}[]>([]);
  const [editing, setEditing] = useState<string | null>(null); const [left, setLeft] = useState(window.innerWidth > 760); const [right, setRight] = useState(false); const [wide, setWide] = useState(false);
 const [collapsed, setCollapsed] = useState<string[]>([]); const [newFile, setNewFile] = useState(false); const [filename, setFilename] = useState(''); const [task, setTask] = useState(''); const [taskResult, setTaskResult] = useState('');
 const sessionId = useRef(crypto.randomUUID());
 const running = useRef(false);
 const stopped = useRef(false);
 const upload = useRef<HTMLInputElement>(null);
 const [repairs, setRepairs] = useState<Record<string, RepairState>>({});
 const imageRequests = useRef<Record<string, ImageInstruction>>({});
 const repairVersions = useRef<Record<string, number>>({});
 const liveCells = useRef(cells); liveCells.current = cells;
 const liveFiles = useRef(files); liveFiles.current = files;
 const [review, setReview] = useState<Review | null>(null);
 const pendingQuote = useRef<string | null>(null);
 // Opens paper/main.tex; the editor highlights the quote once it mounts.
 function showQuote(quote: string) {
   pendingQuote.current = quote; setSelected(null); setMode('Paper');
 }
 function highlightQuote(editor: monaco.editor.IStandaloneCodeEditor) {
   const quote = pendingQuote.current; pendingQuote.current = null;
   const match = quote && editor.getModel()?.findMatches(quote, false, false, true, null, false)[0];
   if(!match){if(quote)setNotice('That quote is no longer in the combined paper.');return;}
   editor.setSelection(match.range); editor.revealRangeInCenter(match.range);
   const highlight = editor.createDecorationsCollection([{ range: match.range, options: { inlineClassName: 'quote-highlight' } }]);
   setTimeout(() => highlight.clear(), 4000);
 }
 function dismissRepair(id: string) {
   delete imageRequests.current[id];
   repairVersions.current[id] = (repairVersions.current[id] || 0) + 1;
   setRepairs(current => { const next = {...current}; delete next[id]; return next; });
 }
 async function proposeRepair(cell: Cell, error: string, commandLine?: number, imageInput?: ImageInstruction) {
   const version = (repairVersions.current[cell.id] || 0) + 1;
   repairVersions.current[cell.id] = version;
   const snapshot = JSON.stringify(liveFiles.current);
   const cellsSnapshot = JSON.stringify(liveCells.current.filter(c=>c.type==='latex').map(c=>[c.id,c.source]));
   const current = () => !stopped.current && JSON.stringify(liveCells.current.filter(c=>c.type==='latex').map(c=>[c.id,c.source]))===cellsSnapshot && repairVersions.current[cell.id] === version && liveCells.current.some(c => c.id === cell.id && c.type === 'latex' && c.source === cell.source);
   const set = (value: Partial<RepairState>) => { if(current())setRepairs(previous => ({...previous,[cell.id]:{...previous[cell.id],...value}})); };
   set({cellsSnapshot,commandLine,original:cell.source,phase:'generating',filesSnapshot:snapshot,proposal:undefined,error:undefined,verified:false,logs:undefined});
   try {
     const proposal = await request<RepairProposal>(base, imageInput ? '/api/compose/image' : commandLine ? '/api/compose/latex' : '/api/repair/latex', {source:cell.source,error,line:commandLine,...imageInput});
     if(!current())return;
     if(!proposal.edits?.length)throw new Error(proposal.summary || 'No safe automatic fix was found.');
     set({proposal,phase:'checking'});
     try {
       const result = await request<{pdfUrl:string;logs?:string}>(base,'/api/compile',{sessionId:sessionId.current,source:notebookLatex(liveCells.current.map(c=>c.id===cell.id?{...c,source:proposal.source}:c)),files:JSON.parse(snapshot)});
       if(!result.pdfUrl)throw new Error('Compiler returned no PDF.');
       set({phase:'ready',verified:true,pdfUrl:result.pdfUrl,logs:result.logs});
     } catch (reason) {
       set({phase:'failed',verified:false,error:'The suggested fix did not compile. Your source has not changed.',logs:(reason as Error).message});
     }
   } catch (reason) { set({phase:'failed',error:(reason as Error).message}); }
 }
 async function retryRepair(cell: Cell) {
   if(running.current || busy)return;
   running.current=true;stopped.current=false;setBusy(cell.id);
   try { await proposeRepair(cell,cell.error || 'LaTeX compilation failed.', repairs[cell.id]?.commandLine, imageRequests.current[cell.id]); }
   finally {running.current=false;setBusy(null);}
 }
 async function generateFromImage(id: string, input: ImageInstruction) {
   if(running.current || busy)return;
   let cell=liveCells.current.find(c=>c.id===id && c.type==='latex');
   if(id && !cell)throw new Error('Choose an existing LaTeX cell.');
   if(!cell){cell={id:crypto.randomUUID(),type:'latex',source:'% Screenshot layout\n'};liveCells.current=[...liveCells.current,cell];setCells(liveCells.current);}
   setMode('Notebook');setSelected(null);
   running.current=true;stopped.current=false;setBusy(cell.id);
   try{imageRequests.current[cell.id]=input;await proposeRepair(cell,'',undefined,input);}finally{running.current=false;setBusy(null);}
 }
 async function generateLatex(cell: Cell, line: number) {
   if(running.current || busy)return;
   running.current=true;stopped.current=false;setBusy(cell.id);
   try { await proposeRepair(cell,'',line); }
   finally { running.current=false;setBusy(null); }
 }
 function acceptRepair(cell: Cell) {
   const repair=repairs[cell.id];
   if(!repair?.verified || !repair.proposal || busy)return;
   if(cell.source!==repair.original || JSON.stringify(files)!==repair.filesSnapshot || JSON.stringify(liveCells.current.filter(c=>c.type==='latex').map(c=>[c.id,c.source]))!==repair.cellsSnapshot){dismissRepair(cell.id);setNotice('The cell or project files changed. Run the cell again to validate a fresh fix.');return;}
   setCells(current=>current.map(c=>c.id===cell.id?{...c,source:repair.proposal!.source,error:undefined,output:'Accepted fix. PDF compilation passed.',status:'success'}:c));
   if(repair.pdfUrl){const origin=base?new URL(base,window.location.href).origin:window.location.origin;setPdf(new URL(repair.pdfUrl,origin).href);setShowPreview(true);setPreviewTab('Preview');}
   setLogs(repair.logs || 'Compilation passed.');setCompileError('');dismissRepair(cell.id);
 }

 useEffect(() => { onSave(project.id, cells, files); }, [project.id, cells, files, onSave]);
 useEffect(() => { localStorage.setItem('pre.api', JSON.stringify(base)); }, [base]);
 const baseRef = useRef(base); baseRef.current = base;
 useEffect(() => () => { stopped.current = true; if(baseRef.current)void request('', '/api/runtime/release', { sessionId: sessionId.current }).catch(() => {}); void request(baseRef.current, '/api/runtime/release', { sessionId: sessionId.current }).catch(() => {}); }, []);

 useEffect(() => { if (notice) { const id = setTimeout(() => setNotice(''), 7000); return () => clearTimeout(id); } }, [notice]);
 function update(id: string, source: string) { dismissRepair(id); setCells(c => c.map(x => x.id === id ? { ...x, source } : x)); }
 function add(type: Cell['type'], source = '') { setCells(c => [...c, { id: crypto.randomUUID(), type, source }]); setSelected(null); setMode('Notebook'); }
 function cellResult(id: string, result: Partial<Cell>) {
   if(result.type) dismissRepair(id);
   setCells(current => current.map(cell => cell.id === id ? { ...cell, ...result } : cell));
 }
 // The workspace is keyed by project ID, so this runs once each time a project opens.
 useEffect(() => { void compile(); }, []);
 async function compileDocument(source?: string, projectFiles = liveFiles.current) {
   setCompileError('');
   const result = await request<{ pdfUrl: string; logs?: string }>(base, '/api/compile', {
     sessionId: sessionId.current, files: projectFiles, ...(source === undefined ? { entrypoint: 'paper/main.tex' } : { source }),
   });
   if (!result.pdfUrl) throw new Error('Compilation returned no PDF URL.');
   const origin = base ? new URL(base, window.location.href).origin : window.location.origin;
   setPdf(new URL(result.pdfUrl, origin).href);
   setLogs(result.logs || 'Compilation complete.'); setPreviewTab('Preview'); setShowPreview(true);
 }
 async function compile(target = mode) {
   if (running.current) return;
   running.current = true; setBusy('compile');
   try {
     if(target === 'Paper') await compileDocument(paperLatex(liveFiles.current, liveCells.current));
     else {
       const command = liveCells.current.find(cell => cell.type === 'latex' && cell.source.split('\n').some(line => /^\s*pre\s+\S/i.test(line)));
       if(command){stopped.current=false;await proposeRepair(command,'',command.source.split('\n').findIndex(line=>/^\s*pre\s+\S/i.test(line))+1);return;}
       await compileDocument(notebookLatex(liveCells.current) ?? '\\null');
     }
   }
   catch (error) { const message = (error as Error).message; setLogs(message); setCompileError(message); }
   finally { running.current = false; setBusy(null); }
 }
 async function execute(cell: Cell) {
   dismissRepair(cell.id);
   cellResult(cell.id, { status: 'running', executedSource: cell.source, output: undefined, error: undefined, images: [], durationMs: undefined });
   try {
     if (cell.type === 'markdown') { setEditing(null); cellResult(cell.id, { status: 'success' }); return true; }
     if (cell.type === 'latex') {
       const commandLine = cell.source.split('\n').findIndex(line => /^\s*pre\s+\S/i.test(line));
       if(commandLine >= 0){ await proposeRepair(cell,'',commandLine+1); cellResult(cell.id,{status:undefined}); return false; }
       const start = performance.now(); await compileDocument(notebookLatex(liveCells.current) ?? '\\null');
       cellResult(cell.id, { status: 'success', output: 'PDF ready in Preview.', durationMs: Math.round(performance.now() - start) }); return true;
     }
     const result = await request<ExecutionResult>(base, '/api/execute', {
       sessionId: sessionId.current, code: cell.source, language: cell.type, files,
     });
     cellResult(cell.id, { output: [result.stdout, result.stderr].filter(Boolean).join('\n'), error: result.error,
       images: result.images || [], durationMs: result.durationMs, executionCount: result.executionCount,
       status: result.error ? 'error' : 'success' });
     return !result.error;
   } catch (error) {
     const message = (error as Error).message;
     cellResult(cell.id, { status: 'error', error: message });
     if (cell.type === 'latex') { setLogs(message); if(!stopped.current)await proposeRepair(cell,message); }
     return false;
   }
 }
 async function run(cell?: Cell) {
   if (running.current || busy) return;
   running.current = true; stopped.current = false; setBusy(cell?.id || 'all');
   try { for (const current of cell ? [cell] : cells) {
     if (stopped.current) break;
     if (!await execute(current)) { if (!cell) setNotice('Run all stopped at the cell with an error.'); break; }
   } } finally { running.current = false; setBusy(null); }
 }
 async function resetRuntime() {
   stopped.current = true;
   setRepairs(current => Object.fromEntries(Object.entries(current).map(([id,repair]) => [id, ['generating','checking'].includes(repair.phase) ? {...repair,phase:'failed' as const,error:'Repair stopped. Your source is unchanged.'} : repair])));
   try {
     await request(base, '/api/runtime/reset', { sessionId: sessionId.current });
     setCells(current => current.map(cell => ({ ...cell, executionCount: undefined })));
     setNotice('Runtime restarted. Variables cleared; previous outputs remain for reference.');
   } catch (error) { setNotice((error as Error).message); }
 }
 async function chat(text = message) { if (!text.trim() || busy) return; const history = [...messages, { role: 'user', text }]; setMessages(history); setMessage(''); setBusy('chat'); try { const r = await request<{ message: string; cells?: {language: Cell['type']; source: string}[] }>(base, '/api/chat', { messages: history, mode, context: assistantContext({cells,files,review,logs,compileError,selected,toolResult:taskResult}) }); setMessages([...history, { role: 'assistant', text: r.message, cells: r.cells }]); } catch (e) { setMessages([...history, { role: 'assistant', text: (e as Error).message }]); } finally { setBusy(null); } }
 function download(name: string, content: string, type = 'text/plain') { const url = URL.createObjectURL(new Blob([content], { type })); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
 let combinedPaper = ''; let paperAssemblyError = '';
 if(mode === 'Paper' && !selected){try{combinedPaper=paperLatex(files, cells);}catch(error){paperAssemblyError=(error as Error).message;}}
 const activeFile = files.find(f => f.path === selected);
 const prompts: Record<string, string> = { Review: 'Evaluate the methodology, evidence, and clarity of this paper. Identify actionable improvements.', Experiment: 'Help me design an experiment with a clear hypothesis and evaluation criteria.', Replicate: 'Create a reproducibility plan with dependencies, datasets, and evaluation criteria.', Iterate: 'Propose the next iteration based on the current methodology and experimental results.', Defend: 'Ask challenging thesis defense questions about our assumptions, methodology, and findings.' };
 return <div className="app"><header className="topbar"><a className="brand" href="#" title="Back to projects" onClick={e => {e.preventDefault();onHome();}}>PRE <small>Compose</small></a><nav><button className={mode === 'Notebook' ? 'nav-item active' : 'nav-item'} disabled={!!busy} onClick={() => {setMode('Notebook');setSelected(null);setPdf('');void compile('Notebook');}}>Notebook</button><button className={mode === 'Paper' ? 'nav-item active' : 'nav-item'} disabled={!!busy} onClick={() => {setMode('Paper');setSelected(null);setShowPreview(true);setPdf('');void compile('Paper');}}>Paper</button><ToolsMenu value={mode} onChange={value=>{setMode(value);setSelected(null);setTaskResult('');}}/></nav><button className="outline-btn" onClick={() => setRight(!right)}><MessageSquare size={15}/> Ask AI</button><div className="topbar-actions"><button className="outline-btn" onClick={() => setShowPreview(!showPreview)}><FileText size={14}/>{showPreview ? 'Hide preview' : 'Preview'}</button><button className="outline-btn" onClick={() => download(`${project.name.replace(/[^a-zA-Z0-9_-]/g, '_')}.json`, JSON.stringify({ version: 1, cells, files }, null, 2), 'application/json')}><Download size={14}/> Export</button><button className="primary-btn" disabled={busy === 'chat' || busy === 'tool'} onClick={() => busy ? resetRuntime() : run()}><Play size={13} fill="currentColor"/>{busy && !['chat','tool'].includes(busy) ? 'Stop' : 'Run all'}</button></div><button className="icon-btn" title="Settings" onClick={() => showSettings(true)}><Settings size={18}/></button></header>
 <div className="workspace"><aside className={`files-panel ${left ? '' : 'hidden'}`}><button className="back-projects" onClick={onHome}>← All projects</button><div className="panel-heading">Files <button className="icon-btn" title="New file" onClick={() => setNewFile(true)}><Plus size={17}/></button></div><label className="file-search"><Search size={14}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Find a file…"/></label><div className="project-root"><ChevronDown size={14}/><Folder size={16}/> {project.name} <span className="tiny-tag">LOCAL</span></div><button className={`tree-item notebook-link ${!selected && mode === 'Notebook' ? 'chosen' : ''}`} onClick={() => {setSelected(null);setMode('Notebook');}}><BookOpen size={16}/> notebook.ipynb</button>{[...new Set([...files.filter(f => f.path.includes('/')).map(f => f.path.split('/')[0])]), ''].map(folder => <div key={folder}>{folder && <button className="tree-item folder" onClick={() => setCollapsed(c => c.includes(folder) ? c.filter(x => x !== folder) : [...c, folder])}>{collapsed.includes(folder) ? <ChevronRight size={13}/> : <ChevronDown size={13}/>}<Folder size={16}/>{folder}</button>}{!collapsed.includes(folder) && files.filter(f => (folder ? f.path.startsWith(folder + '/') : !f.path.includes('/')) && f.path.toLowerCase().includes(query.toLowerCase())).map(f => <button key={f.path} className={`tree-item file ${selected === f.path ? 'chosen' : ''}`} onClick={() => {setSelected(f.path);setMode('Paper');}}><FileText size={15}/>{f.path.split('/').pop()}</button>)}</div>)}<div className="explorer-bottom"><button className="bottom-item" onClick={() => upload.current?.click()}><Upload size={16}/> Upload files</button><button className="bottom-item" onClick={() => showSettings(true)}><Settings size={16}/> Workspace settings</button></div></aside>
 <main>
 <div className={`panes ${showPreview ? '' : 'editor-only'} ${wide && showPreview ? 'preview-wide' : ''} ${mode === 'Replicate' ? 'replicate-layout' : ''}`}><section className="editor-pane"><div className="section-tabs"><button className="icon-btn" title="Toggle explorer" onClick={() => setLeft(!left)}><PanelLeft size={16}/></button><span className="document-tab"><BookOpen size={15}/>{activeFile ? activeFile.path.split('/').pop() : mode === 'Paper' ? 'Combined paper' : mode === 'Notebook' ? 'notebook.ipynb' : `PRE ${mode}`} <span className="tab-dot"/></span><span className="spacer"/><button className="runtime-reset" title="Clear Python and JavaScript variables" onClick={resetRuntime}><RotateCcw size={13}/>{busy && !['chat','tool'].includes(busy) ? 'Stop' : 'Restart'}</button><span className="small-muted">{cells.length} cells</span><button className="icon-btn" title="Export notebook" onClick={() => download('notebook.ipynb', JSON.stringify({ nbformat: 4, nbformat_minor: 5, metadata: {}, cells: cells.map(c => ({ id: c.id, cell_type: ['python','javascript'].includes(c.type) ? 'code' : 'markdown', metadata: { pre_type: c.type }, source: c.source.split('\n').map(l => l + '\n'), ...(['python','javascript'].includes(c.type) ? { execution_count: c.executionCount ?? null, outputs: c.output ? [{ output_type: 'stream', name: 'stdout', text: [c.output] }] : [] } : {}) })) }, null, 2))}><MoreHorizontal size={18}/></button></div>
 <div className="editor-content">{mode === 'Paper' && !selected ? <div className="file-editor"><div className="add-toolbar"><span>Combined paper</span><span className="small-muted">{files.filter(f=>f.path.endsWith('.tex')).length} LaTeX files + {cells.filter(c=>c.type==='latex').length} notebook LaTeX cells</span><span className="spacer"/><button disabled={!!paperAssemblyError} onClick={()=>download('paper.tex',combinedPaper)}><Download size={14}/>Export LaTeX</button></div>{paperAssemblyError ? <p className="repair-error" role="alert">{paperAssemblyError}</p> : <Editor height="100%" theme="pearl" language="latex" value={combinedPaper} onMount={highlightQuote} options={{readOnly:true,domReadOnly:true,minimap:{enabled:false},fontSize:13,padding:{top:18},wordWrap:'on',automaticLayout:true}}/>}</div> : activeFile ? <div className="file-editor"><div className="add-toolbar"><span>{activeFile.path}</span>{mode === 'Paper' && <button onClick={()=>setSelected(null)}>View combined paper</button>}<span className="spacer"/><button onClick={() => download(activeFile.path.split('/').pop()!, activeFile.content)}><Download size={14}/>Save file</button><button title="Delete file" onClick={() => {setFiles(files.filter(f => f.path !== selected));setSelected(null);}}><Trash2 size={14}/></button></div><Editor height="100%" theme="pearl" language={activeFile.path.endsWith('.js') ? 'javascript' : activeFile.path.endsWith('.py') ? 'python' : activeFile.path.endsWith('.tex') ? 'latex' : 'markdown'} value={activeFile.content} onChange={value => setFiles(files.map(f => f.path === selected ? {...f, content: value || ''} : f))} options={{ minimap: {enabled: false}, fontSize: 13, padding: {top: 18}, wordWrap: 'on', automaticLayout: true }}/></div> : mode === 'Replicate' ? <ReplicatePanel base={base} files={files} onAnalyze={()=>{setRight(true);void chat('Analyze the latest replication run. Compare actual measurements and figures against the paper’s expected results and methodology. Explain differences, missing evidence, and whether the code changed since execution. Suggest concrete next steps without claiming reproduction from execution success alone.');}} onSaveFiles={updates=>setFiles(current=>[...current.filter(file=>!updates.some(update=>update.path===file.path)),...updates])} onInsert={source=>add('python',source)}/> : mode === 'Review' ? <ReviewPanel base={base} files={files} cells={cells} review={review} onReview={setReview} onShowQuote={showQuote} onError={setNotice}/> : mode !== 'Notebook' && mode !== 'Paper' ? <div className="tool-workspace"><h2>{mode}</h2><p>{prompts[mode]}</p><label>What would you like to explore?<textarea value={task} onChange={e => setTask(e.target.value)} placeholder={prompts[mode]}/></label><button className="primary-btn" disabled={!!busy} onClick={async () => {setBusy('tool');try {const r = await request<{result: string}>(base, `/api/tools/${mode.toLowerCase()}`, {prompt: task || prompts[mode], files, cells});setTaskResult(r.result);}catch(e){setNotice((e as Error).message);}finally{setBusy(null);}}}><Sparkles size={15}/>{busy === 'tool' ? 'Working…' : `Start ${mode.toLowerCase()}`}</button>{taskResult && <div className="tool-result"><ReactMarkdown>{taskResult}</ReactMarkdown></div>}<div className="context-note"><FileText size={16}/> Uses the files and cells in this research project.</div></div> : <><div className="add-toolbar"><span className="small-muted">INSERT</span><button onClick={() => add('python', 'print("Hello, research!")\n')}><Plus size={13}/> Python</button><button onClick={() => add('javascript', 'console.log("Hello, research!");')}><Plus size={13}/> JavaScript</button><button onClick={() => add('latex', '\\section{New section}\n')}><Plus size={13}/> LaTeX</button><button onClick={() => add('markdown', '## New section\n')}><Plus size={13}/> Markdown</button></div><div className="notebook-scroll">{cells.map((cell) => <React.Fragment key={cell.id}><article className={`cell ${cell.type}`}><div className="cell-header"><select className="cell-language" aria-label="Cell language" value={cell.type} disabled={!!busy} onChange={e => cellResult(cell.id, { type: e.target.value as Cell['type'], output: undefined, error: undefined, images: [], status: undefined, executionCount: undefined })}>{['markdown','python','javascript','latex'].map(type => <option key={type} value={type}>{type === 'latex' ? 'LaTeX' : type === 'javascript' ? 'JavaScript' : type[0].toUpperCase() + type.slice(1)}</option>)}</select>{cell.status === 'running' ? <span className="execution-state">Running…</span> : cell.executionCount ? <span className="execution-state">[{cell.executionCount}]</span> : null}<span className="spacer"/>{['markdown','latex'].includes(cell.type) && <button className="ai-edit" onClick={() => {if(cell.type === 'latex'){const line=cell.source.split('\n').findIndex(text=>/^\s*pre\s+\S/i.test(text));if(line>=0)void generateLatex(cell,line+1);else setNotice('In the LaTeX cell, type pre followed by your instruction on its own line, then press Enter.');}else{setRight(true);setMessage(`Improve this ${cell.type} cell:\n${cell.source}`);}}}><Sparkles size={12}/> AI {cell.type === 'markdown' ? 'write' : 'edit'}</button>}<button className="cell-run" title="Run cell" disabled={!!busy} onClick={() => run(cell)}><Play size={12} fill="currentColor"/>{cell.status === 'running' ? 'Running' : cell.type === 'markdown' ? 'Render' : cell.type === 'latex' ? 'Compile' : 'Run'}</button><button className="icon-btn cell-delete" title="Delete cell" onClick={() => setCells(cells.filter(c => c.id !== cell.id))}><Trash2 size={12}/></button></div>{repairs[cell.id]?.proposal ? null : cell.type === 'markdown' && editing !== cell.id ? <div className="markdown-render" onDoubleClick={() => setEditing(cell.id)}><button className="edit-markdown" title="Edit markdown" onClick={() => setEditing(cell.id)}><SquarePen size={13}/></button><ReactMarkdown>{cell.source || 'Double-click to write…'}</ReactMarkdown></div> : <CellEditor cell={cell} onGenerate={(source, line) => generateLatex({...cell,source}, line)} onChange={source => update(cell.id, source)} onResize={editorHeight => cellResult(cell.id, { editorHeight })}/>}{repairs[cell.id] && <RepairReview repair={repairs[cell.id]} disabled={!!busy} onAccept={() => acceptRepair(cell)} onReject={() => dismissRepair(cell.id)} onRetry={() => retryRepair(cell)}/>}
{(cell.output !== undefined || cell.error) && <div className={`cell-output ${cell.error ? 'output-error' : ''}`} aria-live="polite"><div>{cell.error ? <X size={13}/> : <Check size={13}/>} {cell.error ? 'Error' : 'Output'}{cell.durationMs !== undefined && <span className="execution-duration">{(cell.durationMs / 1000).toFixed(2)}s</span>}<button className="icon-btn" title="Clear output" onClick={() => cellResult(cell.id, { output: undefined, error: undefined, images: [], status: undefined })}><X size={12}/></button></div>{cell.output && <pre>{cell.output}</pre>}{cell.error && (cell.type === 'latex' ? <details className="cell-error-details"><summary>Compiler error details</summary><pre>{cell.error}</pre></details> : <pre>{cell.error}</pre>)}{!cell.output && !cell.error && !cell.images?.length && <p className="empty-output">Completed without output.</p>}{cell.images?.map((image, i) => <img className="plot-output" key={i} src={image} alt={`Plot ${i + 1} from this cell`}/>)}</div>}</article></React.Fragment>)}<button className="add-cell" onClick={() => add('python')}><Plus size={15}/> Add a cell</button></div></>}
 </div><TerminalPanel sessionId={sessionId.current}/></section><section className={`preview-pane ${showPreview ? '' : 'hidden'}`}><div className="section-tabs">{['Preview','Logs','Data'].map(tab => <button key={tab} className={`preview-tab ${previewTab === tab ? 'selected' : ''}`} onClick={() => setPreviewTab(tab)}>{tab}</button>)}<span className="spacer"/><button className="icon-btn" title="Toggle assistant" onClick={() => setRight(!right)}><PanelRight size={16}/></button></div><div className="preview-toolbar"><button className="compile-btn" disabled={!!busy} onClick={() => compile()}><RefreshCw size={12} className={busy === 'compile' ? 'spin' : ''}/>{busy === 'compile' ? 'Compiling' : 'Compile'}</button><span className="spacer"/><select aria-label="Preview zoom" value={zoom} onChange={e => setZoom(Number(e.target.value))}>{[65,85,100,125].map(v => <option key={v} value={v}>{v === 100 ? 'Fit' : `${v}%`}</option>)}</select><button className="icon-btn" title="Download PDF" onClick={() => pdf ? window.open(pdf, '_blank', 'noopener,noreferrer') : setNotice('Compile your paper to generate a downloadable PDF.')}><Download size={15}/></button><button className="icon-btn" title="Expand preview" onClick={() => setWide(!wide)}><Maximize2 size={14}/></button></div><div className="preview-content">{previewTab === 'Logs' ? <pre className="logs">{logs}</pre> : previewTab === 'Data' ? <div className="data-view"><h3>Project data</h3><p>{files.filter(f => f.path.startsWith('data/')).length} data files</p>{files.filter(f => f.path.startsWith('data/')).map(f => <button key={f.path} onClick={() => setSelected(f.path)}>{f.path}</button>)}<button className="outline-btn" onClick={() => upload.current?.click()}><Upload size={14}/> Upload data</button></div> : pdf ? <PdfPreview url={pdf} zoom={zoom}/> : <div className="preview-empty"><FileText size={32}/><h3>{busy === 'compile' ? 'Preparing your paper…' : compileError ? 'Could not compile paper' : 'Your paper preview'}</h3><p role="status">{busy === 'compile' ? 'Your PDF will appear here automatically.' : compileError || 'Compile your LaTeX to see the PDF here.'}</p>{busy !== 'compile' && <button className="primary-btn" disabled={!!busy} onClick={() => compile()}>{compileError ? 'Try again' : 'Compile paper'}</button>}</div>}</div><div className="preview-footer"><FileText size={12}/>{pdf ? 'Compiled PDF' : 'PDF preview'}<span className="spacer"/>{busy === 'compile' ? 'Compiling…' : compileError ? 'Compilation failed' : pdf ? 'Ready' : 'Ready to compile'}</div></section></div></main>
 <aside className={`assistant-panel ${right ? '' : 'hidden'}`}><div className="assistant-title"><span>Ask AI</span><button className="icon-btn" title="Close assistant" onClick={() => setRight(false)}><X size={16}/></button></div><div className="chat-scroll">{messages.length === 0 ? <div className="assistant-welcome"><h3>How can I help?</h3><p>Ask about your writing, code, or results.</p><div className="suggestions">{['Analyze my latest replication results','Compare my results with the paper','Explain the latest error','Write Python code to plot my data'].map(text => <button key={text} onClick={() => setMessage(text)}>{text}<ArrowUpRight size={13}/></button>)}</div></div> : messages.map((m,i) => <div key={i} className={`chat-message ${m.role}`}><strong>{m.role === 'user' ? 'You' : 'PRE'}</strong><ReactMarkdown>{m.text}</ReactMarkdown>{m.cells?.map((cell,index)=><div className="chat-code" key={index}><span>{cell.language}</span><pre><code>{cell.source}</code></pre></div>)}{!!m.cells?.length && <button className="outline-btn" disabled={!!busy || m.inserted} onClick={()=>{setCells(current=>[...current,...m.cells!.map(cell=>({id:crypto.randomUUID(),type:cell.language,source:cell.source}))]);setSelected(null);setMode('Notebook');setMessages(current=>current.map((entry,index)=>index===i?{...entry,inserted:true}:entry));}}><Plus size={13}/>{m.inserted?'Added to notebook':`Insert ${m.cells.length===1?'cell':'cells'}`}</button>}</div>)}{busy === 'chat' && <p className="thinking">Thinking…</p>}</div><ImageCompose cells={cells} busy={!!busy} message={message} onMessage={setMessage} onSend={()=>void chat()} onGenerate={generateFromImage}/></aside></div>
 <input ref={upload} type="file" multiple hidden onChange={async e => {const incoming = await Promise.all(Array.from(e.target.files || []).map(async f => ({path: /\.(csv|tsv|json)$/i.test(f.name) ? `data/${f.name}` : f.name, content: await f.text()})));setFiles(current => [...current.filter(f => !incoming.some(n => n.path === f.path)), ...incoming]);setNotice(`${incoming.length} text file(s) imported.`);e.target.value = '';}} accept=".tex,.bib,.py,.md,.txt,.csv,.tsv,.json,.yml,.yaml,.sty"/>
 {notice && <div className="toast" role="status">{notice}<button className="icon-btn" onClick={() => setNotice('')}><X size={15}/></button></div>}
 {settings && <div className="modal-overlay"><div className="modal" role="dialog" aria-modal="true" aria-labelledby="settings-title"><button className="modal-close icon-btn" onClick={() => showSettings(false)}><X size={18}/></button><Settings size={24}/><h2 id="settings-title">Settings</h2><p>Python, JavaScript, and LaTeX run locally. An external backend is optional for AI or remote execution.</p><label>Backend API URL (optional)<input placeholder="Leave empty to use local execution" value={base} onChange={e => setBase(e.target.value)}/></label><p className="small-muted">Your notebook and files are automatically saved in this browser. Export a backup to keep a portable copy.</p><button className="primary-btn" onClick={() => showSettings(false)}><Check size={15}/> Done</button></div></div>}
 {newFile && <div className="modal-overlay"><form className="modal" onSubmit={e => {e.preventDefault();const path = filename.trim();if(!path || files.some(f => f.path === path)){setNotice('Choose a unique file name.');return;}setFiles([...files,{path,content:''}]);setSelected(path);setMode('Paper');setNewFile(false);setFilename('');}}><button type="button" className="modal-close icon-btn" onClick={() => setNewFile(false)}><X size={18}/></button><h2>Create a file</h2><label>File path<input autoFocus placeholder="paper/sections/introduction.tex" value={filename} onChange={e => setFilename(e.target.value)} required/></label><button className="primary-btn" type="submit"><Plus size={15}/> Create file</button></form></div>}
 </div>;
}
createRoot(document.getElementById('root')!).render(<ProjectApp Workspace={App}/>);
