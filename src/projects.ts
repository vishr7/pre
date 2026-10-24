import type { Cell, ProjectFile } from './api';
import { initialCells, initialFiles, cleanStarterCells, cleanStarterFiles } from './starter';
export type Project = { id: string; name: string; updatedAt: string; archived: boolean; cells: Cell[]; files: ProjectFile[] };
const key = 'pre.projects.v1';
export function readProjects(): Project[] {
  const existing = localStorage.getItem(key);
  if (existing) return JSON.parse(existing);
  const oldCells = localStorage.getItem('pre.cells');
  const oldFiles = localStorage.getItem('pre.files');
  const projects: Project[] = oldCells || oldFiles ? [{
    ...newProject('Untitled project'),
    cells: cleanStarterCells(oldCells ? JSON.parse(oldCells) : initialCells),
    files: cleanStarterFiles(oldFiles ? JSON.parse(oldFiles) : initialFiles),
  }] : [];
  writeProjects(projects);
  return projects;
}
export function newProject(name: string): Project {
  return { id: crypto.randomUUID(), name: name.trim() || 'Untitled project', updatedAt: new Date().toISOString(), archived: false,
    cells: structuredClone(initialCells), files: structuredClone(initialFiles) };
}
export function writeProjects(projects: Project[]) { localStorage.setItem(key, JSON.stringify(projects)); }
export function storedCells(cells: Cell[]): Cell[] {
  return cells.map(({ images, ...cell }) => ({ ...cell, status: cell.status === 'running' ? undefined : cell.status }));
}
