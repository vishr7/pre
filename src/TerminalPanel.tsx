import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type MutableRefObject } from 'react';
import { ChevronDown, ChevronUp, Pencil, Plus, RotateCcw, Server, SquarePlus, TerminalSquare, Trash2, X } from 'lucide-react';
import { defaultLabel, loadSshConnections, parseSshCommand, saveSshConnections, sshCommand, sshPresets, validateSsh, type SshConnection, type SshDraft } from './sshConnections';
import { loadInterpreters, saveInterpreters, validInterpreter, type Interpreters, type RemoteRunner } from './remoteRun';
import TerminalTab, { type TabHandle } from './TerminalTab';
import '@xterm/xterm/css/xterm.css';

const emptyDraft: SshDraft = { label: '', user: '', host: '' };
const maxTabs = 8; // matches the server's per-session terminal limit
type Tab = { id: string; title: string; initialCommand?: string };

export default function TerminalPanel({ sessionId, runnerRef }: { sessionId: string; runnerRef?: MutableRefObject<RemoteRunner | null> }) {
  const [tabs, setTabs] = useState<Tab[]>([{ id: 't1', title: 'Shell 1' }]);
  const [activeId, setActiveId] = useState('t1');
  const activeRef = useRef(activeId); activeRef.current = activeId;
  const tabsRef = useRef(tabs); tabsRef.current = tabs;
  const nextTab = useRef(2);
  const handles = useRef(new Map<string, TabHandle>());
  const [statuses, setStatuses] = useState<Record<string, string>>({});
  const [renaming, setRenaming] = useState<string | null>(null);
  const [interpreters, setInterpreters] = useState<Interpreters>(loadInterpreters);
  const interpretersRef = useRef(interpreters);
  const [connections, setConnections] = useState<SshConnection[]>(loadSshConnections);
  const [menuOpen, setMenuOpen] = useState(false);
  const [editing, setEditing] = useState<{ id: string | null; draft: SshDraft } | null>(null);
  const menu = useRef<HTMLDivElement>(null);
  const sshButton = useRef<HTMLButtonElement>(null);
  const [placement, setPlacement] = useState<CSSProperties>({});
  const [pasted, setPasted] = useState('');
  const [pasteNote, setPasteNote] = useState<{ error: boolean; text: string } | null>(null);
  const [visible, setVisible] = useState(false);
  const [height, setHeight] = useState(200);
  const drag = useRef<{y:number;height:number} | null>(null);

  const active = () => handles.current.get(activeRef.current);
  // Internal ids stay unique (the server may still be closing an old one); visible names reuse freed numbers.
  const newId = () => `t${nextTab.current++}`;
  function freeShellName(existing: Tab[]) {
    let n=1;
    while(existing.some(t => t.title === `Shell ${n}`))n++;
    return `Shell ${n}`;
  }
  function addTab(initialCommand?: string, title?: string) {
    if(tabsRef.current.length >= maxTabs)return false;
    const tab={id:newId(),title:title || freeShellName(tabsRef.current),initialCommand};
    tabsRef.current=[...tabsRef.current,tab];
    setTabs(current => [...current,tab]);setActiveId(tab.id);setVisible(true);
    return true;
  }
  function closeTab(id: string) {
    const index=tabs.findIndex(t => t.id === id);
    const rest=tabs.filter(t => t.id !== id);
    if(!rest.length)rest.push({id:newId(),title:freeShellName(rest)});
    tabsRef.current=rest;setTabs(rest);
    if(activeId === id)setActiveId(rest[Math.min(index,rest.length-1)].id);
    setStatuses(({[id]:_,...others}) => others);
  }
  function renameTab(id: string, title: string) {
    setTabs(current => current.map(t => t.id === id ? {...t,title:title.trim().slice(0,40) || t.title} : t));
    setRenaming(null);
  }

  // Lets notebook cells run in whatever the visible tab is logged into (normally an SSH session).
  useEffect(() => {
    if(!runnerRef)return;
    runnerRef.current={
      run(code, language) {
        const handle=active();
        if(!handle)return Promise.reject(new Error('Open the terminal and connect with SSH first.'));
        setVisible(true);
        return handle.runRemote(code,interpretersRef.current[language]);
      },
      activeTitle: () => tabsRef.current.find(t => t.id === activeRef.current)?.title ?? 'terminal',
    };
    return () => {runnerRef.current=null;};
  }, [runnerRef]);
  function setInterpreter(language: keyof Interpreters, value: string) {
    const next={...interpreters,[language]:value};
    setInterpreters(next);
    if(validInterpreter(value)){interpretersRef.current=next;saveInterpreters(next);}
  }

  useEffect(() => {
    if(!menuOpen && !editing)return;
    const close=(event: MouseEvent | KeyboardEvent) => {
      if(event instanceof KeyboardEvent ? event.key === 'Escape' : !menu.current?.contains(event.target as Node)){setMenuOpen(false);setEditing(null);}
    };
    document.addEventListener('mousedown',close);document.addEventListener('keydown',close);
    return () => {document.removeEventListener('mousedown',close);document.removeEventListener('keydown',close);};
  }, [menuOpen,editing]);
  // Keep the popover fully on screen: open toward the side with more room, capped to the viewport.
  useLayoutEffect(() => {
    if(!menuOpen && !editing)return;
    const place = () => {
      const rect=sshButton.current?.getBoundingClientRect();
      if(!rect)return;
      const margin=12, gap=6, width=Math.min(360,window.innerWidth-2*margin);
      const left=Math.max(margin,Math.min(rect.right-width,window.innerWidth-width-margin));
      const above=rect.top-margin-gap, below=window.innerHeight-rect.bottom-margin-gap;
      setPlacement(above > below
        ? {position:'fixed',left,width,bottom:window.innerHeight-rect.top+gap,maxHeight:above}
        : {position:'fixed',left,width,top:rect.bottom+gap,maxHeight:below});
    };
    place();
    window.addEventListener('resize',place);window.addEventListener('scroll',place,true);
    return () => {window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);};
  }, [menuOpen,editing !== null]);

  function startNew() {setMenuOpen(false);setPasted('');setPasteNote(null);setEditing({id:null,draft:{...emptyDraft}});}
  function applyPaste(text: string) {
    setPasted(text);
    if(!text.trim()){setPasteNote(null);return;}
    const parsed=parseSshCommand(text);
    if('error' in parsed){setPasteNote({error:true,text:parsed.error});return;}
    setEditing(current => current && {...current,draft:{...current.draft,...parsed.draft,label:current.draft.label || defaultLabel(parsed.draft.host)}});
    setPasteNote({error:false,text:parsed.ignored.length ? `Filled in below. Not saved: ${parsed.ignored.join(' ')}` : 'Filled in below. Check the fields, then save.'});
  }
  function store(next: SshConnection[]) {setConnections(next);saveSshConnections(next);}
  function connect(connection: SshDraft, inNewTab = false) {
    const command=sshCommand(connection);
    setMenuOpen(false);setEditing(null);setVisible(true);
    if(inNewTab){if(!addTab(command,connection.label))active()?.connect(command);return;}
    setTabs(current => current.map(t => t.id === activeRef.current ? {...t,title:connection.label} : t));
    active()?.connect(command);
  }
  function save(andConnect: boolean) {
    if(!editing)return;
    const draft={...editing.draft,label:editing.draft.label.trim(),jumpHost:editing.draft.jumpHost?.trim() || undefined};
    if(validateSsh(draft))return;
    const id=editing.id ?? crypto.randomUUID();
    store(editing.id ? connections.map(c => c.id === id ? {...draft,id} : c) : [...connections,{...draft,id}]);
    if(andConnect)connect(draft);else setEditing(null);
  }
  const draftError=editing ? validateSsh({...editing.draft,label:editing.draft.label.trim(),jumpHost:editing.draft.jumpHost?.trim() || undefined}) : null;
  const setDraft=(change: Partial<SshDraft>) => setEditing(current => current && {...current,draft:{...current.draft,...change}});
  const status=statuses[activeId] ?? '';

  return <section className={`terminal-panel ${visible ? 'expanded' : ''}`} style={{height:visible ? height : 34}} aria-label="Local terminal">
    {visible && <div className="terminal-resize" role="separator" aria-label="Resize terminal" aria-orientation="horizontal" aria-valuenow={height} aria-valuemin={140} aria-valuemax={600} tabIndex={0}
      onPointerDown={event=>{event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);drag.current={y:event.clientY,height};}}
      onPointerMove={event=>{if(drag.current)setHeight(Math.max(140,Math.min(600,window.innerHeight-180,drag.current.height+drag.current.y-event.clientY)));}}
      onPointerUp={event=>{drag.current=null;event.currentTarget.releasePointerCapture(event.pointerId);}}
      onPointerCancel={()=>{drag.current=null;}}
      onKeyDown={event=>{if(event.key==='ArrowUp'||event.key==='ArrowDown'){event.preventDefault();setHeight(value=>Math.max(140,Math.min(600,value+(event.key==='ArrowUp'?20:-20))));}}}/>}
    <div className="terminal-heading">
      <button className="terminal-toggle" onClick={()=>setVisible(value=>!value)} aria-expanded={visible}><TerminalSquare size={14}/> Terminal {visible ? <ChevronDown size={13}/> : <ChevronUp size={13}/>}</button>
      <div className="terminal-tabs" role="tablist" aria-label="Terminals">
        {tabs.map(tab => <div key={tab.id} className={`terminal-tab ${tab.id === activeId ? 'active' : ''}`} title={statuses[tab.id] || tab.title}>
          {renaming === tab.id
            ? <input className="terminal-tab-rename" defaultValue={tab.title} autoFocus aria-label="Terminal name" onBlur={e=>renameTab(tab.id,e.target.value)} onKeyDown={e=>{if(e.key==='Enter')renameTab(tab.id,e.currentTarget.value);if(e.key==='Escape')setRenaming(null);}}/>
            : <button role="tab" aria-selected={tab.id === activeId} onClick={()=>{setActiveId(tab.id);setVisible(true);}} onDoubleClick={()=>setRenaming(tab.id)}>
                <span className={`terminal-dot ${statuses[tab.id] === 'Local shell' ? 'live' : ''}`}/>{tab.title}
              </button>}
          <button className="terminal-tab-close" title={`Close ${tab.title}`} aria-label={`Close ${tab.title}`} onClick={()=>closeTab(tab.id)}><X size={11}/></button>
        </div>)}
        <button className="icon-btn terminal-add" title={tabs.length >= maxTabs ? `At most ${maxTabs} terminals` : 'New terminal'} disabled={tabs.length >= maxTabs} onClick={()=>addTab()}><Plus size={13}/></button>
      </div>
      {visible && status && status !== 'Local shell' && <span className="terminal-status" role="status">{status}</span>}
      <span className="spacer"/>
      <div className="ssh-menu-wrap" ref={menu}>
        <button ref={sshButton} className="ssh-button" aria-haspopup="menu" aria-expanded={menuOpen} title="Saved SSH connections" onClick={()=>{setEditing(null);setVisible(true);setMenuOpen(value=>!value);}}><Server size={13}/> SSH <ChevronDown size={12}/></button>
        {menuOpen && !editing && <div className="ssh-menu" role="menu" style={placement}>
          {connections.length === 0 && <p className="ssh-empty">Save an SSH command once, then connect with one click. You only type your password.</p>}
          {connections.map(c => <div key={c.id} className="ssh-item">
            <button role="menuitem" className="ssh-connect" onClick={()=>connect(c)} title={`Connect in this tab: ${sshCommand(c)}`}><strong>{c.label}</strong><code>{sshCommand(c)}</code></button>
            <button className="icon-btn" title={`Open ${c.label} in a new terminal`} disabled={tabs.length >= maxTabs} onClick={()=>connect(c,true)}><SquarePlus size={12}/></button>
            <button className="icon-btn" title={`Edit ${c.label}`} onClick={()=>{setMenuOpen(false);setPasted('');setPasteNote(null);setEditing({id:c.id,draft:{label:c.label,user:c.user,host:c.host,port:c.port,jumpHost:c.jumpHost}});}}><Pencil size={12}/></button>
            <button className="icon-btn" title={`Delete ${c.label}`} onClick={()=>store(connections.filter(x => x.id !== c.id))}><X size={12}/></button>
          </div>)}
          <button role="menuitem" className="ssh-add" onClick={startNew}><Plus size={13}/> Add connection</button>
          <div className="ssh-run-settings">
            <span>"Run on SSH" uses the visible terminal with</span>
            {(['python','javascript'] as const).map(language => <label key={language}>{language === 'python' ? 'Python' : 'JavaScript'}
              <input value={interpreters[language]} spellCheck={false} aria-invalid={!validInterpreter(interpreters[language])} onChange={e=>setInterpreter(language,e.target.value)} placeholder={language === 'python' ? 'python3' : 'node'}/>
            </label>)}
            {!validInterpreter(interpreters.python) || !validInterpreter(interpreters.javascript) ? <p className="ssh-note ssh-error">Use a command or path like python3, ~/venv/bin/python, or conda run -n env python.</p> : <p className="ssh-note">Runs in that terminal's current folder on the remote machine.</p>}
          </div>
        </div>}
        {editing && <form className="ssh-menu ssh-form" style={placement} onSubmit={event=>{event.preventDefault();save(true);}}>
          <strong>{editing.id ? 'Edit connection' : 'New SSH connection'}</strong>
          <label>Paste an ssh command <small>optional</small>
            <input value={pasted} onChange={e=>applyPaste(e.target.value)} placeholder="ssh -J abc1234@ssh.ist.psu.edu abc1234@nittanyaicompute.ist.psu.edu" spellCheck={false} autoFocus={!editing.id}/>
          </label>
          {pasteNote && <p className={`ssh-note ${pasteNote.error ? 'ssh-error' : ''}`} role="status">{pasteNote.text}</p>}
          {!editing.id && <div className="ssh-presets">{sshPresets.map(p => <button type="button" key={p.label} onClick={()=>setDraft({label:editing.draft.label || p.label,host:p.host,jumpHost:p.jumpHost})}>{p.label}</button>)}</div>}
          <label>Name<input value={editing.draft.label} onChange={e=>setDraft({label:e.target.value})} placeholder="Nittany AI Compute" autoFocus={!!editing.id}/></label>
          <div className="ssh-row">
            <label>Username<input value={editing.draft.user} onChange={e=>setDraft({user:e.target.value.trim()})} placeholder="abc1234" autoComplete="username"/></label>
            <label className="ssh-port">Port<input inputMode="numeric" value={editing.draft.port ?? ''} onChange={e=>setDraft({port:e.target.value ? Number(e.target.value) : undefined})} placeholder="22"/></label>
          </div>
          <label>Host<input value={editing.draft.host} onChange={e=>setDraft({host:e.target.value.trim()})} placeholder="nittanyaicompute.ist.psu.edu"/></label>
          <label>Jump host <small>optional · host or user@host:port</small><input value={editing.draft.jumpHost ?? ''} onChange={e=>setDraft({jumpHost:e.target.value.trim()})} placeholder="ssh.ist.psu.edu"/></label>
          <code className="ssh-preview">{draftError && (editing.draft.user || editing.draft.host) ? draftError : editing.draft.user && editing.draft.host ? sshCommand(editing.draft) : 'ssh user@host'}</code>
          <p className="ssh-note">Passwords are never saved. You type them at the prompt.</p>
          <div className="ssh-actions">
            <button type="button" className="outline-btn" onClick={()=>setEditing(null)}>Cancel</button>
            <button type="button" className="outline-btn" disabled={!!draftError} onClick={()=>save(false)}>Save</button>
            <button type="submit" className="primary-btn" disabled={!!draftError}>Save & connect</button>
          </div>
        </form>}
      </div>
      {visible && <><button className="icon-btn" title="Clear terminal" onClick={()=>active()?.clear()}><Trash2 size={13}/></button><button className="icon-btn" title="Restart terminal" onClick={()=>active()?.restart()}><RotateCcw size={13}/></button></>}
    </div>
    {tabs.map(tab => <TerminalTab key={tab.id} sessionId={sessionId} terminalId={tab.id} shown={visible && tab.id === activeId} initialCommand={tab.initialCommand}
      onStatus={value => setStatuses(current => ({...current,[tab.id]:value}))}
      register={handle => {if(handle)handles.current.set(tab.id,handle);else handles.current.delete(tab.id);}}/>)}
  </section>;
}
