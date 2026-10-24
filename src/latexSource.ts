import type { Cell } from './api';

// A notebook's LaTeX cells form one document, in notebook order.
export function notebookLatex(cells: Cell[]): string | undefined {
  const sources = cells.filter(cell => cell.type === 'latex' && cell.source.trim()).map(cell => cell.source);
  if (!sources.length) return undefined;
  const documents = sources.filter(source => /^\s*\\documentclass(?:\[|\{)/m.test(source));
  if (documents.length > 1) throw new Error('Keep only one complete LaTeX document in the notebook. Use fragments in the other LaTeX cells.');
  if (!documents.length) return sources.join('\n\n');
  const document = documents[0];
  const fragments = sources.filter(source => source !== document).join('\n\n');
  if (!fragments) return document;
  const end = /^\s*\\end\{document\}/m.exec(document);
  if (!end) throw new Error('Add \\end{document} to the complete document before combining LaTeX cells.');
  return document.slice(0, end.index) + '\n' + fragments + '\n' + document.slice(end.index);
}

export function paperLatex(files: {path: string; content: string}[], cells: Cell[] = []): string {
  const tex = files.filter(file => file.path.endsWith('.tex')).sort((a,b) => {
    if(a.path === 'paper/main.tex') return -1;
    if(b.path === 'paper/main.tex') return 1;
    return a.path.localeCompare(b.path);
  });
  const byPath = new Map(tex.map(file => [file.path, file.content]));
  const visited = new Set<string>();
  const active = new Set<string>();
  const normalize = (path: string) => {
    const parts: string[] = [];
    for(const part of path.split('/')){if(part === '..')parts.pop();else if(part && part !== '.')parts.push(part);}
    return parts.join('/');
  };
  const expand = (path: string): string => {
    if(active.has(path))throw new Error(`Circular LaTeX inclusion in ${path}.`);
    if(visited.has(path))return '';
    active.add(path);visited.add(path);
    const source = byPath.get(path)!;
    const expanded = source.split('\n').map(line => {
      const comment = line.search(/(?<!\\)%/);
      const code = comment < 0 ? line : line.slice(0,comment);
      return code.replace(/\\(input|include)\s*\{([^}]+)\}/g, (original, command: string, target: string) => {
        const name = target.endsWith('.tex') ? target : `${target}.tex`;
        const relative = normalize(`${path.split('/').slice(0,-1).join('/')}/${name}`);
        const resolved = byPath.has(relative) ? relative : normalize(name);
        if(!byPath.has(resolved))return original;
        const content = expand(resolved);
        return command === 'include' && content ? `\n\\clearpage\n${content}\n\\clearpage\n` : `\n${content}\n`;
      }) + (comment < 0 ? '' : line.slice(comment));
    }).join('\n');
    active.delete(path);
    return expanded;
  };
  // Start at the document root so explicit inputs keep their intended positions.
  const root = tex.find(file => /^\s*\\documentclass(?:\[|\{)/m.test(file.content));
  const ordered = root ? [root, ...tex.filter(file => file !== root)] : tex;
  const sources = ordered.filter(file => !visited.has(file.path)).map(file => ({id:file.path,type:'latex' as const,source:expand(file.path)}));
  const latexCells = cells.filter(cell => cell.type === 'latex' && cell.source.trim());
  // A notebook can contain a complete document; do not let the empty starter
  // paper create a second document or hide the notebook's real content.
  const hasCellDocument = latexCells.some(cell => /^\s*\\documentclass(?:\[|\{)/m.test(cell.source));
  const fileSources = hasCellDocument ? sources.filter(file => {
    const body = /\\begin\{document\}([\s\S]*?)\\end\{document\}/.exec(file.source)?.[1];
    return body === undefined || body.replace(/(?<!\\)%[^\n]*/g, '').replace(/\\null\b/g, '').trim() !== '';
  }) : sources;
  try { return notebookLatex([...fileSources, ...latexCells]) ?? '\\null'; }
  catch(error){throw new Error((error as Error).message.replace('notebook','paper').replace('LaTeX cells','LaTeX files'));}
}
