import { useCallback, useEffect, useState } from 'react';
import type { Cell, ProjectFile } from './api';
import { newProject, readProjects, storedCells, writeProjects, type Project } from './projects';
import ProjectHome from './ProjectHome';

type WorkspaceProps = { project: Project; onHome: () => void; onSave: (id: string, cells: Cell[], files: ProjectFile[]) => void };
function routeId() { return window.location.hash.match(/^#\/project\/([\w-]+)$/)?.[1] || null; }
export default function ProjectApp({ Workspace }: { Workspace: React.ComponentType<WorkspaceProps> }) {
  const [projects, setProjects] = useState(readProjects);
  const [active, setActive] = useState(routeId);
  const [error, setError] = useState('');
  useEffect(() => {
    const update = () => setActive(routeId());
    window.addEventListener('hashchange', update);
    const sync = (event: StorageEvent) => { if(event.key === 'pre.projects.v1')setProjects(readProjects()); };
    window.addEventListener('storage', sync);
    return () => {window.removeEventListener('hashchange',update);window.removeEventListener('storage',sync);};
  }, []);
  const persist = useCallback((next: Project[]) => {
    try {writeProjects(next);setProjects(next);setError('');return true;}
    catch {setError('Could not save projects. Browser storage may be full. Export your work before closing.');return false;}
  }, []);
  const save = useCallback((id: string, cells: Cell[], files: ProjectFile[]) => {
    const current = readProjects();
    const previous = current.find(p => p.id === id);
    const clean = storedCells(cells);
    if (!previous || (JSON.stringify(previous.cells) === JSON.stringify(clean) && JSON.stringify(previous.files) === JSON.stringify(files))) return;
    persist(current.map(p => p.id === id ? {...p,cells:clean,files,updatedAt:new Date().toISOString()} : p));
  }, [persist]);
  function open(id: string) { window.location.hash = `/project/${id}`; }
  function home() { window.location.hash = '/'; }
  const project = projects.find(p => p.id === active);
  return <>{project ? <Workspace key={project.id} project={project} onHome={home} onSave={save}/> : <ProjectHome projects={projects} onOpen={open}
    onCreate={name => {const next = newProject(name);if(persist([...readProjects(),next]))open(next.id);}}
    onRename={(id,name) => persist(readProjects().map(p => p.id === id ? {...p,name,updatedAt:new Date().toISOString()} : p))}
    onArchive={(ids,archived) => persist(readProjects().map(p => ids.includes(p.id) ? {...p,archived} : p))}/>} {error && <div className="toast" role="alert">{error}<button onClick={() => setError('')}>Dismiss</button></div>}</>;
}
