import FileTree from './FileTree';
import {moveProjectFile,validProjectPath} from './fileOperations';
import {addSection,organizeManuscript} from './manuscript';
import ResearchDesk from './ResearchDesk';
import LiteraturePanel from './LiteraturePanel';
import {runResearch} from './runResearch';
import {batchCell} from './iterateBatch';
import type {ResearchWorkflow} from './researchWorkflow';
import {aiActions} from './aiWorkspace';
import {linkFiles,changeCells} from './projectSync';
import { figureAssets, compileErrorSummary, type UploadedFigure } from './figureAssets';
import { organizePaperFolder, describeFile } from './arxivImport';
import { codeLanguages, canRun, isCode } from './languages';
import { prepareChatEdits, patchedSources, type ChatEdit, type EditProposal } from './chatEdits';
import { assistantContext } from './assistantContext';
import ScientificTool from './ScientificTool';
import ToolsMenu from './ToolsMenu';
import ImageCompose, { type ImageInstruction } from './ImageCompose';
import { paperLatex } from './latexSource';
import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import Editor, { DiffEditor, loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import ReactMarkdown from 'react-markdown';
import { BookOpen, FileText, FlaskConical, Copy, ShieldCheck, Sparkles, Plus, ChevronDown, ChevronRight, Folder, Play, MoreHorizontal, Upload, Settings, PanelLeft, Download, Maximize2, Send, X, Check, Code2, ArrowUpRight, Search, RefreshCw, Trash2, SquarePen, GitBranch, CircleHelp, MessageSquare, Table2, Image, PanelRight, RotateCcw } from 'lucide-react';
import { request, type Cell, type ExecutionResult, type ProjectFile } from './api';
import './style.css';
import './scientific.css';
import './uploads.css';
import PdfPreview from './PdfPreview';
import CellEditor from './CellEditor';
import TerminalPanel from './TerminalPanel';
import { missingModuleHint, type RemoteRunner } from './remoteRun';
import { Server } from 'lucide-react';
import RepairReview, { type RepairState, type RepairProposal } from './RepairReview';
import ReviewPanel, { type Review } from './ReviewPanel';
import ProjectApp from './ProjectApp';
import type { Project } from './projects';
import DefendPage from './DefendPage';
(self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });
monaco.languages.register({ id: 'latex' });
monaco.languages.setMonarchTokensProvider('latex', { tokenizer: { root: [[/\\[a-zA-Z]+/, 'keyword'], [/%.*$/, 'comment'], [/[{}\[\]]/, 'delimiter'], [/\$[^$]*\$/, 'string']] } });
monaco.editor.defineTheme('pearl', { base: 'vs', inherit: true, rules: [{ token: 'keyword', foreground: 'A35283' }, { token: 'comment', foreground: '8B9A8C' }], colors: { 'editor.background': '#FFFFFF', 'editorLineNumber.foreground': '#C6C1C6', 'editor.lineHighlightBackground': '#FCF9FA', 'diffEditor.insertedLineBackground': '#e6f3e8', 'diffEditor.removedLineBackground': '#fbe7e9', 'diffEditor.insertedTextBackground': '#b9dfc480', 'diffEditor.removedTextBackground': '#efb6be80' } });
function saved<T>(key: string, fallback: T): T { try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback; } catch { return fallback; } }
function App({ project, onHome, onSave }: { project: Project; onHome: () => void; onSave: (id: string, cells: Cell[], files: ProjectFile[]) => void }) {
 const [workspace,setWorkspace]=useState(()=>linkFiles(structuredClone(project.cells),structuredClone(project.files)));
 const {cells,files}=workspace;
 function setCells(value: Cell[] | ((current:Cell[])=>Cell[])){setWorkspace(current=>changeCells(current,typeof value==='function'?value(current.cells):value));}
 function setFiles(value: ProjectFile[] | ((current:ProjectFile[])=>ProjectFile[])){setWorkspace(current=>linkFiles(current.cells,typeof value==='function'?value(current.files):value));}
 const [showPreview, setShowPreview] = useState(true); const [mode, setMode] = useState('Notebook'); const [selected, setSelected] = useState<string | null>(null);
 const [base, setBase] = useState(() => saved('pre.api', '')); const [settings, showSettings] = useState(false);
 const [aiTarget,setAiTarget]=useState<{id:string;selection:string}|null>(null);
 const workflowLock=useRef(false);
 const [workflowRunning,setWorkflowRunning]=useState(false);
 const [paperSelection,setPaperSelection]=useState('');
 const chatBottom=useRef<HTMLDivElement>(null);
 function focusAssistant(text?:string){setRight(true);if(text!==undefined)setMessage(text);requestAnimationFrame(()=>document.querySelector<HTMLTextAreaElement>('[aria-label="Message PRE Assistant"]')?.focus());}
 const [notice, setNotice] = useState(''); const [busy, setBusy] = useState<string | null>(null); const [pdf, setPdf] = useState('');
 const [compileError, setCompileError] = useState('');
 const [previewTab, setPreviewTab] = useState('Preview'); const [zoom, setZoom] = useState(100); const [logs, setLogs] = useState('No compilation yet.');
 const [query, setQuery] = useState(''); const [message, setMessage] = useState(''); const [messages, setMessages] = useState<{role: string; text: string; cells?: {language: Cell['type']; source: string}[]; inserted?: boolean; proposal?: EditProposal; rejected?: boolean; workflow?:ResearchWorkflow; workflowStatus?:string; workflowCells?:string[]}[]>([]);
  const [editing, setEditing] = useState<string | null>(null); const [left, setLeft] = useState(window.innerWidth > 760); const [right, setRight] = useState(false); const [wide, setWide] = useState(false);
 const [projectCollapsed,setProjectCollapsed]=useState(false);
 const [hiddenFolders,setHiddenFolders]=useState<string[]>(()=>saved('pre.hiddenFolders.'+project.id,[]));
 useEffect(()=>{localStorage.setItem('pre.hiddenFolders.'+project.id,JSON.stringify(hiddenFolders));},[hiddenFolders,project.id]);
 const [deleteFolder,setDeleteFolder]=useState<string|null>(null);
 const [deletedFolder,setDeletedFolder]=useState<{folder:string;files:ProjectFile[];cells:Cell[];uploads:UploadedFigure[]}|null>(null);
 const folderImage=useRef<HTMLInputElement>(null);const imageDestination=useRef('figures');
 const [fileMove,setFileMove]=useState<{from:string;to:string}|null>(null);
 const [collapsed, setCollapsed] = useState<string[]>([]); const [newFile, setNewFile] = useState(false); const [filename, setFilename] = useState(''); const [task, setTask] = useState(''); const [iteratePrompt,setIteratePrompt]=useState(''); const [pendingAnalysis,setPendingAnalysis]=useState<ProjectFile[]|null>(null); const [workflow,setWorkflow]=useState<(ResearchWorkflow&{id:string})|null>(null); const [taskResult, setTaskResult] = useState('');
 const sessionId = useRef(crypto.randomUUID());
 const remoteRunner = useRef<RemoteRunner | null>(null);
 const [remoteCell, setRemoteCell] = useState<string | null>(null);
 const running = useRef(false);
 const stopped = useRef(false);
 const upload = useRef<HTMLInputElement>(null);
 const folderUpload = useRef<HTMLInputElement>(null);
 // Uploaded figures stay in memory only (not saved) until project storage moves to the cloud.
 const [uploads, setUploads] = useState<UploadedFigure[]>([]);
 const liveUploads = useRef(uploads); liveUploads.current = uploads;
 async function importFiles(list: File[], folder: boolean, destination?:string) {
   const textTypes = /\.(tex|bib|bst|bbl|cls|clo|sty|py|md|txt|csv|tsv|json|ya?ml)$/i, imageTypes = /\.(png|jpe?g|pdf)$/i;
   const base64 = (file: File) => new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1] || ''); reader.onerror = () => reject(reader.error); reader.readAsDataURL(file); });
   const texts: ProjectFile[] = [], images: UploadedFigure[] = []; let skipped = 0;
   for (const file of list) {
     const full = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
     const relative = destination!==undefined ? [destination,file.name].filter(Boolean).join('/') : folder ? full.split('/').slice(1).join('/') : file.name;
     if (!relative || relative.split('/').some(part => part.startsWith('.'))) { skipped++; continue; }
     if(destination!==undefined&&(liveFiles.current.some(f=>f.path===relative)||liveUploads.current.some(f=>f.path===relative)||texts.some(f=>f.path===relative)||images.some(f=>f.path===relative))){skipped++;continue;}
     if (imageTypes.test(relative) && file.size <= 3000000) images.push({ path: destination!==undefined||folder ? relative : `figures/${relative}`, data: await base64(file) });
     else if (textTypes.test(relative)) texts.push({ path: destination===undefined&&!folder && /\.(csv|tsv|json)$/i.test(relative) ? `data/${relative}` : relative, content: await file.text() });
     else skipped++;
   }
   // A whole paper folder (e.g. an unzipped arXiv source) is sorted into main.tex, sections/, figures/, bibliography/, and styles/.
   if (folder && destination === undefined) {
     const root = files.some(f => f.path === 'main.tex') ? 'main.tex' : files.some(f => f.path === 'paper/main.tex') ? 'paper/main.tex' : 'main.tex';
     const sorted = organizePaperFolder(texts, images, root);
     texts.splice(0, texts.length, ...sorted.files); images.splice(0, images.length, ...sorted.figures);
     if (sorted.main && !window.confirm(`Replace ${root} with ${sorted.main} from this folder?`)) texts.splice(texts.findIndex(t => t.path === root), 1);
   }
   setFiles(current => [...current.filter(f => !texts.some(n => n.path === f.path)), ...texts]);
   setUploads(current => [...current.filter(u => !images.some(i => i.path === u.path)), ...images]);
   setNotice(`${texts.length} file(s) added${images.length ? `, ${images.length} figure(s) kept until you refresh` : ''}${skipped ? `, ${skipped} skipped` : ''}.`);
 }
 const [repairs, setRepairs] = useState<Record<string, RepairState>>({});
 const chatEditProposals = useRef<Record<string, RepairProposal>>({});
 const imageRequests = useRef<Record<string, ImageInstruction>>({});
 const repairVersions = useRef<Record<string, number>>({});
 const liveCells = useRef(cells); liveCells.current = cells;
 const liveFiles = useRef(files); liveFiles.current = files;
 const [review, setReview] = useState<Review | null>(null);
 // A "Fix this" edit to a file, shown as a red/green diff in the editor until the author accepts or rejects it.
 const [pendingFix, setPendingFix] = useState<{ path: string; original: string; modified: string; commentId: string } | null>(null);
 function resolveComment(id: string) {
   setReview(current => current && { ...current, comments: current.comments.filter(c => c.id !== id),
     action_items: current.action_items.map(a => ({ ...a, related_comment_ids: a.related_comment_ids.filter(x => x !== id) })) });
 }
 async function applyReviewFix(proposal: EditProposal, commentId: string) {
   const first = proposal.edits[0];
   if (first.target === 'cell') return reviewChatEdits(proposal, undefined, 'Suggested fix from PRE Review');
   try {
     const modified = patchedSources(proposal, liveCells.current, liveFiles.current)['file:' + first.id];
     setPendingFix({ path: first.id, original: liveFiles.current.find(f => f.path === first.id)!.content, modified, commentId });
     setMode('Notebook'); setSelected(first.id);
     return true;
   } catch (error) { setNotice((error as Error).message); return false; }
 }
 // Applies instantly; the PDF refreshes in the background, so existing LaTeX errors never block a fix.
 function acceptFix() {
   if (!pendingFix) return;
   const current = liveFiles.current.find(f => f.path === pendingFix.path)?.content;
   if (current !== pendingFix.original) { setPendingFix(null); setNotice('The file changed since this fix was suggested. Run Fix this again.'); return; }
   const nextFiles = liveFiles.current.map(f => f.path === pendingFix.path ? { ...f, content: pendingFix.modified } : f);
   setFiles(nextFiles); resolveComment(pendingFix.commentId); setPendingFix(null);
   setNotice('Fix applied. The comment was removed from your review.');
   if (!running.current) { running.current = true; setBusy('compile');
     compileDocument(paperLatex(nextFiles, liveCells.current), nextFiles)
       .catch(error => { const message = (error as Error).message; setLogs(message); setCompileError(message); setNotice('Fix applied, but the paper has LaTeX errors. See Logs.'); })
       .finally(() => { running.current = false; setBusy(null); }); }
 }
 function revealFirstChange(editor: monaco.editor.IStandaloneDiffEditor) {
   const reveal = () => { const change = editor.getLineChanges()?.[0]; if (change) editor.getModifiedEditor().revealLineInCenter(Math.max(1, change.modifiedStartLineNumber)); };
   reveal(); editor.onDidUpdateDiff(reveal);
 }
 const pendingQuote = useRef<string | null>(null);
 // Opens the matching manuscript section and highlights the quoted passage.
 function showQuote(quote: string) {
   const cell=liveCells.current.find(c=>c.type==='latex'&&c.source.includes(quote));
   const file=liveFiles.current.find(f=>f.path.endsWith('.tex')&&f.content.includes(quote));
   if(!cell&&!file){setNotice('That passage has changed. Run the review again.');return;}
   pendingQuote.current = quote; setSelected(cell?.filePath||file?.path||null);if(cell)setAiTarget({id:cell.id,selection:''}); setMode('Notebook');
   if(cell)requestAnimationFrame(()=>document.getElementById('cell-'+cell.id)?.scrollIntoView({block:'center'}));
 }
 function highlightQuote(editor: monaco.editor.IStandaloneCodeEditor) {
   const subscription=editor.onDidChangeCursorSelection(()=>{if(editor.hasTextFocus()){const range=editor.getSelection();setPaperSelection(range?editor.getModel()?.getValueInRange(range).slice(0,12000)||'':'');}});
   editor.onDidDispose(()=>subscription.dispose());
   const quote = pendingQuote.current; pendingQuote.current = null;
   const match = quote && editor.getModel()?.findMatches(quote, false, false, true, null, false)[0];
   if(!match){if(quote)setNotice('That quote is no longer in this section.');return;}
   editor.setSelection(match.range); editor.revealRangeInCenter(match.range);
   const highlight = editor.createDecorationsCollection([{ range: match.range, options: { inlineClassName: 'quote-highlight' } }]);
   setTimeout(() => highlight.clear(), 4000);
 }
 function dismissRepair(id: string) {
   delete imageRequests.current[id];
   delete chatEditProposals.current[id];
   repairVersions.current[id] = (repairVersions.current[id] || 0) + 1;
   setRepairs(current => { const next = {...current}; delete next[id]; return next; });
 }
 async function proposeRepair(cell: Cell, error: string, commandLine?: number, imageInput?: ImageInstruction, suppliedProposal?: RepairProposal) {
   const version = (repairVersions.current[cell.id] || 0) + 1;
   repairVersions.current[cell.id] = version;
   const snapshot = JSON.stringify(liveFiles.current);
   const cellsSnapshot = JSON.stringify(liveCells.current.filter(c=>c.type==='latex').map(c=>[c.id,c.source]));
   const current = () => !stopped.current && JSON.stringify(liveCells.current.filter(c=>c.type==='latex').map(c=>[c.id,c.source]))===cellsSnapshot && repairVersions.current[cell.id] === version && liveCells.current.some(c => c.id === cell.id && c.type === 'latex' && c.source === cell.source);
   const set = (value: Partial<RepairState>) => { if(current())setRepairs(previous => ({...previous,[cell.id]:{...previous[cell.id],...value}})); };
   set({cellsSnapshot,commandLine,original:cell.source,phase:'generating',filesSnapshot:snapshot,proposal:undefined,error:undefined,verified:false,logs:undefined});
   try {
     const proposal = suppliedProposal ?? await request<RepairProposal>(base, imageInput ? '/api/compose/image' : commandLine ? '/api/compose/latex' : '/api/repair/latex', {source:cell.source,error,line:commandLine,...imageInput});
     if(!current())return;
     if(!proposal.edits?.length)throw new Error(proposal.summary || 'No safe automatic fix was found.');
     set({proposal,phase:'checking'});
     try {
       const result = await request<{pdfUrl:string;logs?:string}>(base,'/api/compile',{sessionId:sessionId.current,assets:figureAssets(liveCells.current,JSON.parse(snapshot),liveUploads.current),source:paperLatex(changeCells({cells:liveCells.current,files:JSON.parse(snapshot)},liveCells.current.map(c=>c.id===cell.id?{...c,source:proposal.source}:c)).files,liveCells.current.map(c=>c.id===cell.id?{...c,source:proposal.source}:c)),files:JSON.parse(snapshot)});
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
   try { await proposeRepair(cell,cell.error || 'LaTeX compilation failed.', repairs[cell.id]?.commandLine, imageRequests.current[cell.id], chatEditProposals.current[cell.id]); }
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
 // A reload or closed tab skips React unmount; keepalive lets the release finish while the page unloads.
 useEffect(() => {
   const leave = () => { for (const target of new Set(['', baseRef.current])) void fetch(`${target.replace(/\/$/, '')}/api/runtime/release`, { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json', ...(target ? {} : { 'X-PRE-Runtime': '1' }) }, body: JSON.stringify({ sessionId: sessionId.current }) }).catch(() => {}); };
   window.addEventListener('pagehide', leave);
   return () => window.removeEventListener('pagehide', leave);
 }, []);
 useEffect(() => () => { stopped.current = true; if(baseRef.current)void request('', '/api/runtime/release', { sessionId: sessionId.current }).catch(() => {}); void request(baseRef.current, '/api/runtime/release', { sessionId: sessionId.current }).catch(() => {}); }, []);

 useEffect(() => { if (notice) { const id = setTimeout(() => setNotice(''), 7000); return () => clearTimeout(id); } }, [notice]);
 function update(id: string, source: string) { dismissRepair(id); setCells(c => c.map(x => x.id === id ? { ...x, source } : x)); }
 function removeFolder(folder:string){const prefix=folder+'/';const removed={folder,files:liveFiles.current.filter(f=>f.path.startsWith(prefix)),cells:liveCells.current.filter(c=>c.filePath?.startsWith(prefix)),uploads:liveUploads.current.filter(u=>u.path.startsWith(prefix))};setDeletedFolder(removed);setHiddenFolders(current=>[...current,folder]);setFiles(current=>current.filter(f=>!f.path.startsWith(prefix)));setUploads(current=>current.filter(u=>!u.path.startsWith(prefix)));if(selected?.startsWith(prefix))setSelected(null);setDeleteFolder(null);setNotice('Folder contents deleted. Undo is available in the sidebar.');}
 function undoFolderDelete(){if(!deletedFolder)return;const paths=new Set([...liveFiles.current.map(f=>f.path),...liveUploads.current.map(f=>f.path)]);if([...deletedFolder.files,...deletedFolder.uploads].some(f=>paths.has(f.path))){setNotice('A restored file would overwrite an existing path. Rename that file before undoing.');return;}setWorkspace(current=>linkFiles([...current.cells,...deletedFolder.cells.filter(c=>!current.cells.some(n=>n.id===c.id))],[...current.files,...deletedFolder.files]));setUploads(current=>[...current,...deletedFolder.uploads]);setHiddenFolders(current=>current.filter(f=>f!==deletedFolder.folder));setDeletedFolder(null);}
 function createInFolder(folder=''){setFilename(folder?folder+'/':'');setNewFile(true);}
 function moveFile(from:string,to:string){try{to=validProjectPath(to);if(liveUploads.current.some(f=>f.path===to))throw new Error('A figure already exists at that path.');const next=moveProjectFile({cells:liveCells.current,files:liveFiles.current},from,to);setWorkspace(next);if(selected===from)setSelected(to);setFileMove(null);setNotice('File moved. Literal LaTeX file references were updated.');}catch(e){setNotice((e as Error).message);}}
 function openProjectFile(path:string){
   const cell=liveCells.current.find(c=>c.type==='latex'&&c.filePath===path);
   setMode('Notebook');
   if(!cell){setSelected(path);return;}
   setSelected(path);setAiTarget({id:cell.id,selection:''});
   requestAnimationFrame(()=>document.getElementById('cell-'+cell.id)?.scrollIntoView({block:'center',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'}));
 }
 function addManuscriptSection(){const next=addSection({cells:liveCells.current,files:liveFiles.current});setWorkspace(next);setSelected(next.files[next.files.length-1].path);setMode('Notebook');}
 function organizeSections(){try{setWorkspace(organizeManuscript({cells:liveCells.current,files:liveFiles.current}));setSelected('main.tex');setMode('Notebook');setNotice('Organized into main.tex and sections/. Original sources are saved in history/.');}catch(e){setNotice((e as Error).message);}}
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
     sessionId: sessionId.current, files: projectFiles, assets:figureAssets(liveCells.current,projectFiles,liveUploads.current), ...(source === undefined ? { entrypoint: projectFiles.some(f=>f.path==='main.tex')?'main.tex':'paper/main.tex' } : { source }),
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
       await compileDocument(paperLatex(liveFiles.current,liveCells.current));
     }
   }
   catch (error) { const message = (error as Error).message; setLogs(message); setCompileError(message); }
   finally { running.current = false; setBusy(null); }
 }
 async function execute(cell: Cell) {
   if(!canRun(cell.type)){setNotice(`${cell.type} is available for editing; run it in the terminal with its language runtime.`);return true;}
   dismissRepair(cell.id);
   cellResult(cell.id, { status: 'running', executedSource: cell.source, output: undefined, error: undefined, images: [], durationMs: undefined, ranOn: undefined });
   try {
     if (cell.type === 'markdown') { setEditing(null); cellResult(cell.id, { status: 'success' }); return true; }
     if (cell.type === 'latex') {
       const commandLine = cell.source.split('\n').findIndex(line => /^\s*pre\s+\S/i.test(line));
       if(commandLine >= 0){ await proposeRepair(cell,'',commandLine+1); cellResult(cell.id,{status:undefined}); return false; }
       const start = performance.now(); await compileDocument(paperLatex(liveFiles.current,liveCells.current));
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
 // Run a cell on the machine the terminal is logged into, reusing that SSH session.
 async function runRemote(cell: Cell) {
   if (remoteCell || (cell.type !== 'python' && cell.type !== 'javascript')) return;
   if (!remoteRunner.current) { setNotice('Open the terminal and connect with SSH first.'); return; }
   setRemoteCell(cell.id);
   cellResult(cell.id, { status: 'running', executedSource: cell.source, output: undefined, error: undefined, images: [], durationMs: undefined, executionCount: undefined, ranOn: remoteRunner.current.activeTitle() });
   const start = performance.now();
   try {
     const result = await remoteRunner.current.run(cell.source, cell.type);
     const durationMs = Math.round(performance.now() - start);
     const error = result.cancelled ? 'Interrupted with Ctrl+C. See the terminal for any output.'
       : result.exitCode ? [`Exited with code ${result.exitCode} on the SSH machine.`, missingModuleHint(result.output)].filter(Boolean).join('\n\n') : undefined;
     cellResult(cell.id, { output: result.output.replace(/\n$/, ''), error, durationMs, status: error ? 'error' : 'success' });
   } catch (e) {
     cellResult(cell.id, { status: 'error', error: (e as Error).message });
   } finally { setRemoteCell(null); }
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
 // Also used by Review's "Fix this" (no chat index); returns whether the edits were applied or opened for review.
 async function reviewChatEdits(proposal: EditProposal, index?: number, summary = 'Requested edit from Ask AI') {
   if(busy || running.current)return false;
   try {
     const sources=patchedSources(proposal,liveCells.current,liveFiles.current);
     const keys=Object.keys(sources);const first=proposal.edits[0];
     const cell=first.target==='cell'?liveCells.current.find(c=>c.id===first.id):undefined;
     if(keys.length===1 && cell?.type==='latex' && !first.remove){
       setMode('Notebook');setSelected(cell.filePath||null);setAiTarget({id:cell.id,selection:''});running.current=true;stopped.current=false;setBusy(cell.id);
       chatEditProposals.current[cell.id]={summary,edits:proposal.edits.map(({old_text,new_text,reason})=>({old_text,new_text,reason})),source:sources[keys[0]]};
       await proposeRepair(cell,'',undefined,undefined,chatEditProposals.current[cell.id]);
       requestAnimationFrame(()=>document.getElementById('cell-'+cell.id)?.scrollIntoView({block:'center',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'}));
     }else{
       running.current=true;setBusy('edit');
       const removed=new Set(proposal.edits.filter(e=>e.remove).map(e=>e.target+':'+e.id));
       for(const c of liveCells.current){if(c.filePath&&(removed.has('cell:'+c.id)||removed.has('file:'+c.filePath))){removed.add('cell:'+c.id);removed.add('file:'+c.filePath);}}
       const nextCells=liveCells.current.filter(c=>!removed.has('cell:'+c.id)).map(c=>sources['cell:'+c.id]!==undefined?{...c,source:sources['cell:'+c.id],output:undefined,error:undefined,status:undefined,images:[]}:c);
       const nextFiles=liveFiles.current.filter(f=>!removed.has('file:'+f.path)).map(f=>sources['file:'+f.path]!==undefined?{...f,content:sources['file:'+f.path]}:(()=>{const c=nextCells.find(c=>c.filePath===f.path);return c?{...f,content:c.source}:f;})());
       const latex=proposal.edits.some(e=>e.target==='file'?e.id.endsWith('.tex'):liveCells.current.find(c=>c.id===e.id)?.type==='latex');
       if(latex){const snapshot=JSON.stringify({cells:liveCells.current,files:liveFiles.current});await compileDocument(paperLatex(nextFiles,linkFiles(nextCells,nextFiles).cells),nextFiles);if(snapshot!==JSON.stringify({cells:liveCells.current,files:liveFiles.current}))throw new Error('The project changed during compilation. Review a fresh suggestion.');patchedSources(proposal,liveCells.current,liveFiles.current);}
       setWorkspace(linkFiles(nextCells,nextFiles));setMode('Notebook');setSelected(first.target==='file'&&!first.remove?first.id:null);
     }
     if(index!==undefined)setMessages(current=>current.map((m,i)=>i===index?{...m,inserted:true}:m));
     return true;
   }catch(error){const message=(error as Error).message;setLogs(message);setNotice(compileErrorSummary(message));return false;}finally{running.current=false;setBusy(null);}
 }
 async function launchResearch(plan:ResearchWorkflow,index:number,execute:boolean){
   if(workflowLock.current||busy)return;
   workflowLock.current=true;setWorkflowRunning(true);
   const configurations=JSON.parse(plan.configurations);
   const code=batchCell(plan.code,configurations,plan.metric,plan.direction,plan.parallel);
   const existing=messages[index]?.workflowCells;
   const folder='experiments/'+crypto.randomUUID();
   const ids=existing||[folder+'/trial.py',folder+'/run.py'];
   const status=(workflowStatus:string)=>setMessages(current=>current.map((m,i)=>i===index?{...m,workflowStatus,workflowCells:ids}:m));
   try{
    if(existing&&(!liveFiles.current.some(f=>f.path===ids[0]&&f.content===plan.code)||!liveFiles.current.some(f=>f.path===ids[1]&&f.content===code)))throw new Error('The saved experiment changed. Ask AI for a fresh plan before running.');
    if(!existing)setFiles(current=>[...current,{path:ids[0],content:plan.code},{path:ids[1],content:code},{path:ids[0].replace('/trial.py','/plan.json'),content:JSON.stringify({...plan,createdAt:new Date().toISOString(),sources:liveFiles.current.filter(f=>f.path==='literature/selected.json')},null,2)}]);
    status(execute?'Starting tests…':'Experiment saved. Ready to run.');
    if(!execute)return;
    const report=await runResearch(plan,remoteRunner.current,(path,body)=>request('',path,body),status);
    const reportFile={path:'iteration/latest-results.json',content:JSON.stringify(report,null,2)};
    const next=[...liveFiles.current.filter(f=>f.path!==reportFile.path),reportFile];setFiles(current=>[...current.filter(f=>f.path!==reportFile.path&&f.path!==ids[0].replace('/trial.py','/results.json')),reportFile,{path:ids[0].replace('/trial.py','/results.json'),content:JSON.stringify(report,null,2)}]);
    status(report.status==='completed'?`Finished on ${report.ranOn}. ${report.trials.filter((t:{status:string})=>t.status==='success').length}/${report.trials.length} tests succeeded.`:'Tests stopped. Recorded results saved.');
    if(plan.writeAnalysis&&report.status==='completed'){setPendingAnalysis(next);}
   }catch(error){const message=(error as Error).message;status(message);}
   finally{workflowLock.current=false;setWorkflowRunning(false);}
 }
 async function chat(text = message, reportFiles?:ProjectFile[]) { if (!text.trim() || busy) return; const history = [...messages, { role: 'user', text }]; setMessages(history); setMessage(''); setBusy('chat'); try { const r = await request<{ message: string; cells?: {language: Cell['type']; source: string}[]; edits?: ChatEdit[]; workflow?:ResearchWorkflow }>(base, '/api/chat', { messages: history, mode, context: {...assistantContext({cells,files:reportFiles||files,review,logs,compileError,selected,toolResult:taskResult}),activeTarget:mode==='Notebook'&&!activeFile&&visibleCell?{target:'cell',id:visibleCell.id,selection:aiTarget?.id===visibleCell.id?aiTarget.selection:''}:selected?{target:'file',id:selected,selection:paperSelection}:null} });
 setMessages([...history, { role: 'assistant', text: r.workflow?'Your experiment plan is ready. Review the comparison below, then approve the run. AI will save the scripts and results for you.':r.message, workflow:r.workflow, cells: r.cells, proposal:r.edits?.length?prepareChatEdits(r.edits,cells,files):undefined }]); } catch (e) { setMessages([...history, { role: 'assistant', text: (e as Error).message }]); } finally { setBusy(null); } }
 function download(name: string, content: string, type = 'text/plain') { const url = URL.createObjectURL(new Blob([content], { type })); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
 useEffect(()=>{if(!pendingAnalysis||busy)return;const report=pendingAnalysis.find(f=>f.path==='iteration/latest-results.json');const snapshot=report?[...liveFiles.current.filter(f=>f.path!==report.path),report]:liveFiles.current;setPendingAnalysis(null);void chat('The requested experiment has finished. Use iteration/latest-results.json to propose targeted edits adding analysis to the existing paper. Report measured values, failed trials, execution location and limitations. Do not generate another experiment or claim unrecorded results.',snapshot);},[pendingAnalysis,busy]);
 useEffect(()=>{chatBottom.current?.scrollIntoView({block:'end',behavior:'auto'});},[messages,busy]);
 useEffect(()=>{const shortcut=(event:KeyboardEvent)=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='j'){event.preventDefault();focusAssistant();}};window.addEventListener('keydown',shortcut);return()=>window.removeEventListener('keydown',shortcut);},[]);
 const selectedFile = files.find(f => f.path === selected);
 const activeFile = selectedFile?.path.endsWith('.tex') && pendingFix?.path!==selectedFile.path ? undefined : selectedFile;
 const visibleCell=cells.find(c=>c.type==='latex'&&c.filePath===selected)||(!selected?cells.find(c=>c.type==='latex'&&c.id===aiTarget?.id):undefined)||cells.find(c=>c.type==='latex'&&c.filePath==='main.tex')||cells.find(c=>c.type==='latex');
 const prompts: Record<string, string> = { Review: 'Evaluate the methodology, evidence, and clarity of this paper. Identify actionable improvements.', Experiment: 'Help me design an experiment with a clear hypothesis and evaluation criteria.', Replicate: 'Create a reproducibility plan with dependencies, datasets, and evaluation criteria.', Iterate: 'Propose the next iteration based on the current methodology and experimental results.', Defend: 'Ask challenging thesis defense questions about our assumptions, methodology, and findings.' };
 return <div className="app"><header className="topbar"><a className="brand" href="#" title="Back to projects" aria-label="PRE Compose — back to projects" onClick={e => {e.preventDefault();onHome();}}><span className="brand-mark" aria-hidden="true"><span>P</span><i /></span><span className="brand-wordmark"><strong>PRE</strong><span>COMPOSE</span></span></a><nav><button className={mode === 'Notebook' ? 'nav-item active' : 'nav-item'} disabled={!!busy} onClick={() => {setMode('Notebook');setSelected(null);setPdf('');void compile('Notebook');}}>Sections</button><ToolsMenu value={mode} onChange={value=>{setMode(value);setSelected(null);setTaskResult('');}}/></nav><button className="outline-btn" onClick={() => setRight(!right)}><MessageSquare size={15}/> Ask AI</button><div className="topbar-actions">{['Notebook','Review'].includes(mode)&&<button className="outline-btn" onClick={() => setShowPreview(!showPreview)}><FileText size={14}/>{showPreview ? 'Hide preview' : 'Preview'}</button>}<button className="outline-btn" onClick={() => download(`${project.name.replace(/[^a-zA-Z0-9_-]/g, '_')}.json`, JSON.stringify({ version: 1, cells, files }, null, 2), 'application/json')}><Download size={14}/> Export</button><button className="primary-btn" disabled={busy === 'chat' || busy === 'tool'} onClick={() => busy ? resetRuntime() : compile()}><Play size={13} fill="currentColor"/>{busy && !['chat','tool'].includes(busy) ? 'Stop' : 'Compile paper'}</button></div><button className="icon-btn" title="Settings" onClick={() => showSettings(true)}><Settings size={18}/></button></header>
 <div className="workspace"><aside className={`files-panel ${left ? '' : 'hidden'}`}><button className="back-projects" onClick={onHome}>← All projects</button><div className="panel-heading">Files <div className="file-actions"><button className="icon-btn" title="New file" aria-label="New file" onClick={() => createInFolder()}><Plus size={15}/></button><button className="icon-btn" title="Upload files" aria-label="Upload files" onClick={()=>upload.current?.click()}><Upload size={15}/></button><button className="icon-btn" title="Upload folder" aria-label="Upload folder" onClick={()=>folderUpload.current?.click()}><Folder size={15}/></button></div></div><label className="file-search"><Search size={14}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Find a file…"/></label><button className="project-root" aria-expanded={!projectCollapsed} aria-controls="project-file-tree" title={projectCollapsed?'Expand project':'Collapse project'} onClick={()=>setProjectCollapsed(value=>!value)}>{projectCollapsed?<ChevronRight size={14}/>:<ChevronDown size={14}/>}<Folder size={16}/> <span className="project-name">{project.name}</span></button><div id="project-file-tree" className="file-tree" hidden={projectCollapsed}><FileTree hiddenFolders={hiddenFolders} files={files} selected={selected||visibleCell?.filePath} query={query} disabled={!!busy||workflowRunning} onOpen={openProjectFile} onCreate={folder=>{setFilename(folder+'/untitled.txt');setNewFile(true);}} onImage={folder=>{imageDestination.current=folder;folderImage.current?.click();}} onDelete={setDeleteFolder} onMove={moveFile} onMoveRequest={path=>setFileMove({from:path,to:path})} onUpload={(incoming,folder)=>void importFiles(incoming,false,folder).catch(error=>setNotice((error as Error).message))}/>{uploads.length > 0 && <div className="upload-figures"><div className="upload-figures-heading">Figures <small>kept until you refresh</small></div>{uploads.map(u => <div key={u.path} className="upload-figure" title={`${u.path} — ${describeFile(u.path)}`}><Image size={14}/><span>{u.path}</span><button className="icon-btn" title="Remove figure" onClick={() => setUploads(current => current.filter(x => x.path !== u.path))}><X size={12}/></button></div>)}</div>}</div><div className="explorer-bottom">{deletedFolder&&<button className="bottom-item" onClick={undoFolderDelete}>Undo folder deletion</button>}<button className="bottom-item" onClick={() => showSettings(true)}><Settings size={16}/> Workspace settings</button></div></aside>
 <main>
 <div className={`panes ${showPreview ? '' : 'editor-only'} ${wide && showPreview ? 'preview-wide' : ''} ${['Ablations','Literature','Iterate','Experiment','Defend'].includes(mode) ? 'replicate-layout' : ''}`}><section className="editor-pane"><div className="section-tabs"><button className="icon-btn" title="Toggle explorer" onClick={() => setLeft(!left)}><PanelLeft size={16}/></button><span className="document-tab"><BookOpen size={15}/>{selectedFile ? selectedFile.path : mode === 'Notebook' ? visibleCell?.filePath||'LaTeX cell' : `PRE ${mode}`} <span className="tab-dot"/></span><span className="spacer"/><span className="small-muted">{mode==='Notebook'?'LaTeX editor':''}</span></div>
 <div className="editor-content">{activeFile ? <div className="file-editor"><div className="add-toolbar"><span>{activeFile.path}</span><button onClick={()=>setSelected(null)}>Back to sections</button><span className="spacer"/><button onClick={() => download(activeFile.path.split('/').pop()!, activeFile.content)}><Download size={14}/>Save file</button><button title="Delete file" onClick={() => {setFiles(files.filter(f => f.path !== selected));setSelected(null);}}><Trash2 size={14}/></button></div>{pendingFix?.path === activeFile.path ? <><div className="review-fix-bar" role="status"><Sparkles size={14}/><span><strong>Suggested fix from PRE Review</strong> Red is the current text, green is the fix.</span><button className="outline-btn" onClick={() => {setPendingFix(null);setNotice('Fix rejected. Your paper is unchanged.');}}><X size={13}/> Reject</button><button className="primary-btn" onClick={acceptFix}><Check size={13}/> Accept fix</button></div><DiffEditor height="100%" theme="pearl" language="latex" original={pendingFix.original} modified={pendingFix.modified} onMount={revealFirstChange} options={{ readOnly: true, renderSideBySide: false, minimap: {enabled: false}, fontSize: 13, wordWrap: 'on', automaticLayout: true }}/></> : <Editor height="100%" theme="pearl" language={activeFile.path.endsWith('.js') ? 'javascript' : activeFile.path.endsWith('.py') ? 'python' : activeFile.path.endsWith('.tex') ? 'latex' : 'markdown'} value={activeFile.content} onMount={highlightQuote} onChange={value => setFiles(files.map(f => f.path === selected ? {...f, content: value || ''} : f))} options={{ minimap: {enabled: false}, fontSize: 13, padding: {top: 18}, wordWrap: 'on', automaticLayout: true }}/>}</div> : mode === 'Literature' ? <LiteraturePanel files={files} cells={cells} busy={!!busy} onSave={file=>setFiles(current=>[...current.filter(f=>f.path!==file.path),file])} onAsk={(prompt,snapshot)=>{setRight(true);void chat(prompt,snapshot);}} onCompare={()=>{setSelected(null);setMode('Ablations');}}/> : mode === 'Ablations' ? <ResearchDesk key={mode} mode={mode} files={files} busy={!!busy} onLiterature={()=>setMode('Literature')} onAsk={prompt=>{setRight(true);void chat(prompt);}}/> : mode === 'Review' ? <ReviewPanel onIterate={prompt=>{setRight(true);void chat(prompt);}} base={base} files={files} cells={cells} review={review} onReview={setReview} onShowQuote={showQuote} onError={setNotice} onApplyEdits={applyReviewFix}/> : mode === 'Iterate' ? <ResearchDesk key={mode} mode={mode} files={files} busy={!!busy} onLiterature={()=>setMode('Literature')} onAsk={prompt=>{setRight(true);void chat(prompt);}}/> : mode === 'Experiment' ? <ScientificTool key={mode + base} mode={mode} base={base} files={files} cells={cells} onSummary={setTaskResult}/> : mode === 'Defend' ? <DefendPage base={base} files={files} cells={cells}/> : mode !== 'Notebook' ? <div className="tool-workspace"><h2>{mode}</h2><p>{prompts[mode]}</p>{mode !== 'Defend' && <><label>What would you like to explore?<textarea value={task} onChange={e => setTask(e.target.value)} placeholder={prompts[mode]}/></label><button className="primary-btn" disabled={!!busy} onClick={async () => {setBusy('tool');try {const r = await request<{result: string}>(base, `/api/tools/${mode.toLowerCase()}`, {prompt: task || prompts[mode], files, cells});setTaskResult(r.result);}catch(e){setNotice((e as Error).message);}finally{setBusy(null);}}}><Sparkles size={15}/>{busy === 'tool' ? 'Working…' : `Start ${mode.toLowerCase()}`}</button>{taskResult && <div className="tool-result"><ReactMarkdown>{taskResult}</ReactMarkdown></div>}<div className="context-note"><FileText size={16}/> Uses the files and cells in this research project.</div></>}</div> : <><div className="add-toolbar"><button onClick={addManuscriptSection}><Plus size={13}/> Add LaTeX cell</button><button onClick={organizeSections} disabled={!!busy}>Organize manuscript</button><span className="small-muted">Each LaTeX cell stays linked to its source file</span></div><div className="notebook-scroll">{cells.filter(cell=>cell.id===visibleCell?.id).map((cell) => <React.Fragment key={cell.id}><article id={`cell-${cell.id}`} className={`cell ${cell.type}`} aria-busy={cell.status === 'running'} data-execution-status={cell.status}><div className="cell-header"><button className="ai-edit" title="Ask AI about this cell" onClick={()=>{setAiTarget({id:cell.id,selection:''});focusAssistant('Help me improve this cell. Propose edits to this cell rather than creating a copy.');}}><Sparkles size={12}/>Ask AI</button>{cell.filePath&&<span className="small-muted" title="Linked source file: edits update the manuscript and PDF">{cell.filePath}</span>}<span className="small-muted">LaTeX section</span>{cell.status === 'running' ? <span className="execution-state" role="status"><span className="science-status-dot" aria-hidden="true"/>Running...</span> : cell.executionCount ? <span className="execution-state">[{cell.executionCount}]</span> : null}<span className="spacer"/>{['markdown','latex'].includes(cell.type) && <button className="ai-edit" onClick={() => {if(cell.type === 'latex'){const line=cell.source.split('\n').findIndex(text=>/^\s*pre\s+\S/i.test(text));if(line>=0)void generateLatex(cell,line+1);else setNotice('In the LaTeX cell, type pre followed by your instruction on its own line, then press Enter.');}else{setRight(true);setMessage(`Improve this ${cell.type} cell:\n${cell.source}`);}}}><Sparkles size={12}/> AI {cell.type === 'markdown' ? 'write' : 'edit'}</button>}{(cell.type === 'python' || cell.type === 'javascript') && <button className="cell-run-remote" title="Run this cell on the machine the terminal is SSH'd into" disabled={!!remoteCell || cell.status === 'running'} onClick={() => runRemote(cell)}><Server size={11}/>{remoteCell === cell.id ? 'Running on SSH' : 'Run on SSH'}</button>}<button className="cell-run" title={canRun(cell.type)?"Run cell":"Editor only — use the terminal to run this language"} disabled={!!busy || !canRun(cell.type) || remoteCell === cell.id} onClick={() => run(cell)}><Play size={12} fill="currentColor"/>{!canRun(cell.type) ? 'Editor only' : cell.status === 'running' ? 'Running' : cell.type === 'markdown' ? 'Render' : cell.type === 'latex' ? 'Compile' : 'Run'}</button><button className="icon-btn cell-delete" title="Delete cell" onClick={() => setCells(cells.filter(c => c.id !== cell.id))}><Trash2 size={12}/></button></div>{repairs[cell.id]?.proposal ? null : cell.type === 'markdown' && editing !== cell.id ? <div className="markdown-render" onDoubleClick={() => setEditing(cell.id)}><button className="edit-markdown" title="Edit markdown" onClick={() => setEditing(cell.id)}><SquarePen size={13}/></button><ReactMarkdown>{cell.source || 'Double-click to write…'}</ReactMarkdown></div> : <CellEditor onMount={editor=>{if(pendingQuote.current&&cell.source.includes(pendingQuote.current))highlightQuote(editor);}} onContext={selection=>setAiTarget({id:cell.id,selection})} cell={cell} onGenerate={(source, line) => generateLatex({...cell,source}, line)} onChange={source => update(cell.id, source)} onResize={editorHeight => cellResult(cell.id, { editorHeight })}/>}{repairs[cell.id] && <RepairReview repair={repairs[cell.id]} disabled={!!busy} onAccept={() => acceptRepair(cell)} onReject={() => dismissRepair(cell.id)} onRetry={() => retryRepair(cell)}/>}
{(cell.output !== undefined || cell.error) && <div className={`cell-output ${cell.error ? 'output-error' : ''}`} aria-live="polite"><div>{cell.error ? <X size={13}/> : <Check size={13}/>} {cell.error ? 'Error' : 'Output'}<button className="ai-edit" onClick={()=>{setAiTarget({id:cell.id,selection:''});focusAssistant(cell.error?'Diagnose this cell’s error and propose a targeted fix.':'Analyze this cell’s recorded output. Explain the results and limitations.');}}><Sparkles size={12}/>{cell.error?'Fix with AI':'Explain output'}</button>{cell.ranOn && <span className="ran-on">on {cell.ranOn}</span>}{cell.durationMs !== undefined && <span className="execution-duration">{(cell.durationMs / 1000).toFixed(2)}s</span>}<button className="icon-btn" title="Clear output" onClick={() => cellResult(cell.id, { output: undefined, error: undefined, images: [], status: undefined })}><X size={12}/></button></div>{cell.output && <pre>{cell.output}</pre>}{cell.error && (cell.type === 'latex' ? <details className="cell-error-details"><summary>Compiler error details</summary><pre>{cell.error}</pre></details> : <pre>{cell.error}</pre>)}{!cell.output && !cell.error && !cell.images?.length && <p className="empty-output">Completed without output.</p>}{cell.images?.map((image, i) => <img className="plot-output" key={i} src={image} alt={`Plot ${i + 1} from this cell`}/>)}</div>}</article></React.Fragment>)}<button className="add-cell" onClick={addManuscriptSection}><Plus size={15}/> Add a LaTeX cell</button></div></>}
 </div><TerminalPanel sessionId={sessionId.current} runnerRef={remoteRunner}/></section><section className={`preview-pane ${showPreview ? '' : 'hidden'}`}><div className="section-tabs">{['Preview','Logs','Data'].map(tab => <button key={tab} className={`preview-tab ${previewTab === tab ? 'selected' : ''}`} onClick={() => setPreviewTab(tab)}>{tab}</button>)}<span className="spacer"/><button className="icon-btn" title="Toggle assistant" onClick={() => setRight(!right)}><PanelRight size={16}/></button></div><div className="preview-toolbar"><button className="compile-btn" disabled={!!busy} onClick={() => compile()}><RefreshCw size={12} className={busy === 'compile' ? 'spin' : ''}/>{busy === 'compile' ? 'Compiling' : 'Compile'}</button><span className="spacer"/><select aria-label="Preview zoom" value={zoom} onChange={e => setZoom(Number(e.target.value))}>{[65,85,100,125].map(v => <option key={v} value={v}>{v === 100 ? 'Fit' : `${v}%`}</option>)}</select><button className="icon-btn" title="Download PDF" onClick={() => pdf ? window.open(pdf, '_blank', 'noopener,noreferrer') : setNotice('Compile your paper to generate a downloadable PDF.')}><Download size={15}/></button><button className="icon-btn" title="Expand preview" onClick={() => setWide(!wide)}><Maximize2 size={14}/></button></div><div className="preview-content">{previewTab === 'Logs' ? <pre className="logs">{logs}</pre> : previewTab === 'Data' ? <div className="data-view"><h3>Project data</h3><p>{files.filter(f => f.path.startsWith('data/')).length} data files</p>{files.filter(f => f.path.startsWith('data/')).map(f => <button key={f.path} onClick={() => setSelected(f.path)}>{f.path}</button>)}<button className="outline-btn" onClick={() => upload.current?.click()}><Upload size={14}/> Upload data</button></div> : pdf ? <PdfPreview url={pdf} zoom={zoom}/> : <div className="preview-empty"><FileText size={32}/><h3>{busy === 'compile' ? 'Preparing your paper…' : compileError ? 'Could not compile paper' : 'Your paper preview'}</h3><p role="status">{busy === 'compile' ? 'Your PDF will appear here automatically.' : compileError || 'Compile your LaTeX to see the PDF here.'}</p>{busy !== 'compile' && <button className="primary-btn" disabled={!!busy} onClick={() => compile()}>{compileError ? 'Try again' : 'Compile paper'}</button>}</div>}</div><div className="preview-footer"><FileText size={12}/>{pdf ? 'Compiled PDF' : 'PDF preview'}<span className="spacer"/>{busy === 'compile' ? 'Compiling…' : compileError ? 'Compilation failed' : pdf ? 'Ready' : 'Ready to compile'}</div></section></div></main>
 <aside className={`assistant-panel ${right ? '' : 'hidden'}`}><div className="assistant-title"><span>Ask AI</span><button className="icon-btn" title="Close assistant" onClick={() => setRight(false)}><X size={16}/></button></div><div className="assistant-context"><span>{mode}{mode==='Notebook'&&aiTarget?' · Active cell':selected?' · '+selected:' · Project context'}</span>{mode==='Notebook'&&aiTarget&&<button title="Clear focused cell" onClick={()=>setAiTarget(null)}><X size={12}/></button>}{mode==='Notebook'&&aiTarget?.selection&&<small>{aiTarget.selection.slice(0,100)}</small>}{selected&&paperSelection&&<small>{paperSelection.slice(0,100)}</small>}</div><div className="assistant-actions">{aiActions(mode).map(action=><button key={action.label} disabled={!!busy} onClick={()=>focusAssistant(action.prompt)}>{action.label}</button>)}</div><div className="chat-scroll">{messages.length === 0 ? <div className="assistant-welcome"><h3>Work with your research</h3><p>Write your paper, question the evidence, or ask AI to design and run a comparison. Changes are proposed for review.</p><div className="suggestions">{['Help me plan the next step','Summarize the current project'].map(text => <button key={text} onClick={() => setMessage(text)}>{text}<ArrowUpRight size={13}/></button>)}</div></div> : messages.map((m,i) => <div key={i} className={`chat-message ${m.role}`}><strong>{m.role === 'user' ? 'You' : 'PRE'}</strong><ReactMarkdown>{m.text}</ReactMarkdown>{m.workflow&&<section className="chat-workflow"><div className="workflow-meta"><span>{JSON.parse(m.workflow.configurations).length} tests</span><span>{m.workflow.execution==='ssh'?'SSH required':'SSH or local'}</span><span>{m.workflow.parallel} at a time</span></div><p>{m.workflow.summary}</p><p className="science-muted">Each test has a 30-second execution limit. Required data and packages must be available on the execution machine.</p><details><summary>Comparisons & measurement</summary><p>Metric: {m.workflow.metric} · {m.workflow.direction==='minimize'?'lower is better':'higher is better'}</p><ul>{(JSON.parse(m.workflow.configurations) as Record<string,unknown>[]).map((config,n)=><li key={n}>{Object.entries(config).map(([key,value])=>`${key.replaceAll('_',' ')}: ${JSON.stringify(value)}`).join(' · ')}</li>)}</ul></details>{m.workflow.writeAnalysis&&<p className="workflow-next">After running: propose an analysis for your paper. You review edits before they’re applied.</p>}<div className="workflow-buttons"><button className="primary-btn" disabled={!!busy||workflowRunning||m.workflowStatus?.startsWith('Finished')} onClick={()=>void launchResearch(m.workflow!,i,true)}>{m.workflowCells?'Run experiment':'Approve & run'}</button><button className="outline-btn" disabled={!!busy||workflowRunning||!!m.workflowCells} onClick={()=>void launchResearch(m.workflow!,i,false)}>Save for later</button><button className="outline-btn" disabled={workflowRunning} onClick={()=>{focusAssistant('Revise the proposed experiment: '+m.workflow!.summary+'\nChanges I want: ');}}>Refine with AI</button></div>{m.workflowStatus&&<p role="status" className="workflow-status">{m.workflowStatus}</p>}</section>}{m.proposal && <div className="chat-edit-proposal"><strong>Edit existing content</strong>{m.proposal.edits.map((edit,j)=><details key={j}><summary>{edit.remove?'Remove ':''}{edit.target==='cell'?'Notebook cell':'File'} · {edit.reason}</summary><pre className="chat-edit-old">− {edit.old_text}</pre><pre className="chat-edit-new">+ {edit.new_text}</pre></details>)}<div><button className="primary-btn" disabled={!!busy||m.inserted||m.rejected} onClick={()=>void reviewChatEdits(m.proposal!,i)}>{m.inserted?'Sent to editor':m.rejected?'Rejected':m.proposal.edits.every(e=>!e.remove&&e.target==='cell'&&e.id===m.proposal!.edits[0].id)&&cells.find(c=>c.id===m.proposal!.edits[0].id)?.type==='latex'?'Review in cell':'Apply edits'}</button><button className="outline-btn" disabled={!!busy||m.inserted||m.rejected} onClick={()=>setMessages(current=>current.map((entry,index)=>index===i?{...entry,rejected:true}:entry))}>Reject</button></div></div>}{m.cells?.filter(cell=>cell.language==='latex').map((cell,index)=><div className="chat-code" key={index}><span>{cell.language}</span><pre><code>{cell.source}</code></pre></div>)}{!!m.cells?.length && <button className="outline-btn" disabled={!!busy || m.inserted} onClick={()=>{setCells(current=>[...current,...m.cells!.filter(cell=>cell.language==='latex').map(cell=>({id:crypto.randomUUID(),type:cell.language,source:cell.source}))]);setFiles(current=>[...current,...m.cells!.filter(cell=>cell.language!=='latex').map(cell=>({path:'experiments/'+crypto.randomUUID()+(cell.language==='python'?'.py':cell.language==='javascript'?'.js':'.md'),content:cell.source}))]);setSelected(null);setMode('Notebook');setMessages(current=>current.map((entry,index)=>index===i?{...entry,inserted:true}:entry));}}><Plus size={13}/>{m.inserted?'Saved to project':'Add to project'}</button>}</div>)}{busy === 'chat' && <p className="thinking" role="status">Reading project context and preparing a response…</p>}<div ref={chatBottom}/></div><ImageCompose activeCellId={mode==='Notebook'?aiTarget?.id:undefined} cells={cells} busy={!!busy} message={message} onMessage={setMessage} onSend={()=>void chat()} onGenerate={generateFromImage}/></aside></div>
 <input ref={upload} type="file" multiple hidden onChange={e => {void importFiles(Array.from(e.target.files || []), false); e.target.value = '';}} accept=".tex,.bib,.bst,.bbl,.cls,.sty,.py,.md,.txt,.csv,.tsv,.json,.yml,.yaml,.png,.jpg,.jpeg,.pdf"/>
 <input ref={folderUpload} type="file" multiple hidden {...{ webkitdirectory: '' }} onChange={e => {void importFiles(Array.from(e.target.files || []), true); e.target.value = '';}}/>
 {notice && <div className="toast" role="status">{notice}<button className="icon-btn" onClick={() => setNotice('')}><X size={15}/></button></div>}
 {settings && <div className="modal-overlay"><div className="modal" role="dialog" aria-modal="true" aria-labelledby="settings-title"><button className="modal-close icon-btn" onClick={() => showSettings(false)}><X size={18}/></button><Settings size={24}/><h2 id="settings-title">Settings</h2><p>Local compile, execution, and session routes are served by PRE’s Vite runtime. Leave this URL empty for local PRE: voice defense connects to FastAPI on port 8000, while Iterate and HPC use the Vite proxy. Enter a URL only for a separate backend implementing PRE’s external API.</p><label>Backend API URL (optional)<input placeholder="Leave empty for local PRE" value={base} onChange={e => setBase(e.target.value)}/></label><p className="small-muted">Your notebook and files are automatically saved in this browser. Export a backup to keep a portable copy.</p><button className="primary-btn" onClick={() => showSettings(false)}><Check size={15}/> Done</button></div></div>}
 <input ref={folderImage} type="file" multiple hidden accept="image/png,image/jpeg,application/pdf" onChange={e=>{void importFiles(Array.from(e.target.files||[]),false,imageDestination.current).catch(error=>setNotice((error as Error).message));e.target.value='';}}/>
 {deleteFolder!==null&&<div className="modal-overlay"><form className="modal" role="dialog" aria-modal="true" aria-labelledby="delete-folder-title" onSubmit={e=>{e.preventDefault();removeFolder(deleteFolder);}}><h2 id="delete-folder-title">Delete {deleteFolder}/?</h2><p>This removes {files.filter(f=>f.path.startsWith(deleteFolder+'/')).length} files and {uploads.filter(f=>f.path.startsWith(deleteFolder+'/')).length} uploaded figures, including nested folders.</p><p>References to these files may need updating. You can undo this deletion until you leave or refresh the project, or delete another folder.</p><button className="outline-btn" type="button" onClick={()=>setDeleteFolder(null)}>Cancel</button><button className="primary-btn" type="submit" disabled={!!busy||workflowRunning}>Delete folder</button></form></div>}
 {fileMove&&<div className="modal-overlay"><form className="modal" onSubmit={e=>{e.preventDefault();moveFile(fileMove.from,fileMove.to);}}><button type="button" className="modal-close icon-btn" onClick={()=>setFileMove(null)}><X size={18}/></button><h2>Move or rename file</h2><p>{fileMove.from}</p><label>New path<input autoFocus value={fileMove.to} onChange={e=>setFileMove({...fileMove,to:e.target.value})} required/></label><p className="small-muted">Use a folder path such as sections/methods.tex. Existing files will not be overwritten.</p><button className="primary-btn" type="submit">Save location</button></form></div>}
 {newFile && <div className="modal-overlay"><form className="modal" onSubmit={e => {e.preventDefault();let path:string;try{path=validProjectPath(filename);if(files.some(f=>f.path===path||f.path.startsWith(path+'/')||path.startsWith(f.path+'/'))||uploads.some(f=>f.path===path))throw new Error('Choose a unique file path.');}catch(error){setNotice((error as Error).message);return;}setFiles([...files,{path,content:''}]);setSelected(path);setMode('Notebook');setNewFile(false);setFilename('');}}><button type="button" className="modal-close icon-btn" onClick={() => setNewFile(false)}><X size={18}/></button><h2>Create a file</h2><label>File path<input autoFocus placeholder="sections/methods.tex" value={filename} onChange={e => setFilename(e.target.value)} required/></label><button className="primary-btn" type="submit"><Plus size={15}/> Create file</button></form></div>}
 </div>;
}
createRoot(document.getElementById('root')!).render(<ProjectApp Workspace={App}/>);
