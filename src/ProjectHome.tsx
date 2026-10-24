import { useState } from 'react';
import { Archive, ArrowDown, ArrowUp, ArrowUpRight, FileText, Folder, Plus, Search, SquarePen, X } from 'lucide-react';
import type { Project } from './projects';

type Props = {
  projects: Project[];
  onOpen: (id: string) => void;
  onCreate: (name: string) => void;
  onRename: (id: string, name: string) => void;
  onArchive: (ids: string[], archived: boolean) => void;
};
export default function ProjectHome({ projects, onOpen, onCreate, onRename, onArchive }: Props) {
  const [view, setView] = useState<'active' | 'archived'>('active');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [newest, setNewest] = useState(true);
  const [dialog, setDialog] = useState<{ id?: string; name: string } | null>(null);
  const visible = projects.filter(p => p.archived === (view === 'archived') && p.name.toLowerCase().includes(query.toLowerCase()))
    .sort((a, b) => (new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()) * (newest ? 1 : -1));
  const checked = selected.filter(id => visible.some(p => p.id === id));
  const allChecked = visible.length > 0 && checked.length === visible.length;
  function changeView(next: typeof view) { setView(next); setSelected([]); setQuery(''); }
  return <div className="project-home">
    <aside className="home-sidebar">
      <a className="brand" href="#/">PRE <small>Compose</small></a>
      <div className="home-nav-label">WORKSPACE</div>
      <button className={view === 'active' ? 'home-nav selected' : 'home-nav'} onClick={() => changeView('active')}><Folder size={17}/> Your projects <span>{projects.filter(p => !p.archived).length}</span></button>
      <button className={view === 'archived' ? 'home-nav selected' : 'home-nav'} onClick={() => changeView('archived')}><Archive size={17}/> Archived <span>{projects.filter(p => p.archived).length}</span></button>
      <div className="home-local"><span className="status-dot"/> Saved on this device</div>
    </aside>
    <main className="home-main">
      <header className="home-heading"><div><p>YOUR WORKSPACE</p><h1>{view === 'active' ? 'All projects' : 'Archived projects'}</h1></div><button className="primary-btn" onClick={() => setDialog({name:''})}><Plus size={16}/> New project</button></header>
      <div className="home-toolbar"><label className="home-search"><Search size={16}/><input aria-label="Search projects" placeholder="Search projects…" value={query} onChange={e => setQuery(e.target.value)}/>{query && <button title="Clear search" onClick={() => setQuery('')}><X size={14}/></button>}</label>{checked.length > 0 && <button className="outline-btn" onClick={() => {onArchive(checked, view === 'active');setSelected([]);}}><Archive size={14}/>{view === 'active' ? 'Archive' : 'Restore'} {checked.length} selected</button>}</div>
      <div className="project-table-wrap"><table className="project-table"><thead><tr><th className="check-column"><input type="checkbox" aria-label="Select all visible projects" checked={allChecked} disabled={!visible.length} onChange={() => setSelected(allChecked ? [] : visible.map(p => p.id))}/></th><th>Title</th><th className="owner-column">Owner</th><th><button className="sort-button" onClick={() => setNewest(!newest)}>Last modified {newest ? <ArrowDown size={13}/> : <ArrowUp size={13}/>}</button></th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{visible.map(project => <tr key={project.id}><td><input type="checkbox" aria-label={`Select ${project.name}`} checked={checked.includes(project.id)} onChange={() => setSelected(current => current.includes(project.id) ? current.filter(id => id !== project.id) : [...current, project.id])}/></td><td><button className="project-open" onClick={() => onOpen(project.id)}><FileText size={17}/><span>{project.name}</span><ArrowUpRight size={13}/></button></td><td className="owner-column">You</td><td className="modified-date" title={new Date(project.updatedAt).toLocaleString()}>{new Date(project.updatedAt).toLocaleDateString(undefined, {month:'short',day:'numeric',year:'numeric'})}</td><td><div className="project-row-actions"><button className="icon-btn" title={`Rename ${project.name}`} onClick={() => setDialog({id:project.id,name:project.name})}><SquarePen size={15}/></button><button className="icon-btn" title={`${project.archived ? 'Restore' : 'Archive'} ${project.name}`} onClick={() => onArchive([project.id], !project.archived)}><Archive size={15}/></button></div></td></tr>)}</tbody></table>{!visible.length && <div className="home-empty"><Folder size={32}/><h2>{query ? 'No matching projects' : view === 'archived' ? 'No archived projects' : 'A fresh start.'}</h2><p>{query ? 'Try another project name.' : view === 'archived' ? 'Projects you archive will appear here.' : 'Create a project and start writing or running code.'}</p>{!query && view === 'active' && <button className="primary-btn" onClick={() => setDialog({name:''})}><Plus size={15}/> Create your first project</button>}</div>}</div>
      <p className="project-count">{visible.length} {visible.length === 1 ? 'project' : 'projects'}</p>
    </main>
    {dialog && <div className="modal-overlay" onKeyDown={e => {if(e.key === 'Escape')setDialog(null);}}><form className="modal" role="dialog" aria-modal="true" aria-labelledby="project-dialog-title" onSubmit={e => {e.preventDefault();const name=dialog.name.trim();if(!name)return;if(dialog.id)onRename(dialog.id,name);else onCreate(name);setDialog(null);}}><button type="button" className="modal-close icon-btn" title="Close" onClick={() => setDialog(null)}><X size={18}/></button><h2 id="project-dialog-title">{dialog.id ? 'Rename project' : 'New project'}</h2>{!dialog.id && <p>A blank notebook and paper, ready for your work.</p>}<label>Project name<input autoFocus required maxLength={100} placeholder="e.g. My research project" value={dialog.name} onChange={e => setDialog({...dialog,name:e.target.value})}/></label><div className="home-dialog-actions"><button type="button" className="outline-btn" onClick={() => setDialog(null)}>Cancel</button><button type="submit" className="primary-btn" disabled={!dialog.name.trim()}>{dialog.id ? 'Save name' : 'Create project'}</button></div></form></div>}
  </div>;
}
