import type { Cell } from './api';

// A notebook's LaTeX cells form one document, in notebook order.
export function notebookLatex(cells: Cell[]): string | undefined {
  const sources = [...new Map(cells.filter(cell => cell.type === 'latex' && cell.source.trim()).map(cell => [cell.source.trim(), cell.source])).values()];
  if (!sources.length) return undefined;
  const isDocument = (source: string) => /^\s*\\documentclass(?:\[|\{)/m.test(source);
  const rootIndex = sources.findIndex(isDocument);
  if (rootIndex < 0) return sources.join('\n\n');
  const document = sources[rootIndex];
  if (sources.length === 1) return document;
  const begin = /\\begin\{document\}/.exec(document);
  const end = /\\end\{document\}/.exec(document);
  if (!begin || !end || end.index < begin.index) throw new Error('Close the main document with \\begin{document} and \\end{document} before combining content.');
  const extras: string[] = [];
  const preamble = document.slice(0,begin.index);
  const additions: string[] = [];
  // Keep multiline declarations together (titles and macros often span lines).
  const declarations = (source: string) => {
    const chunks: string[] = [];
    let chunk: string[] = [], depth = 0;
    for (const line of source.split('\n')) {
      chunk.push(line);
      const code = line.replace(/(?<!\\)%.*$/, '');
      for (let index = 0; index < code.length; index++) {
        if (code[index] === '\\') { index++; continue; }
        if (code[index] === '{') depth++;
        if (code[index] === '}') depth--;
      }
      if (depth <= 0) { chunks.push(chunk.join('\n')); chunk = []; depth = 0; }
    }
    if (chunk.length) chunks.push(chunk.join('\n'));
    return chunks;
  };
  const knownLines = new Set(declarations(preamble).map(line=>line.trim()));
  for(const [index,source] of sources.entries()) {
    if(index === rootIndex)continue;
    if(!isDocument(source)){extras.push(source);continue;}
    const start = /\\begin\{document\}/.exec(source);
    const finish = /\\end\{document\}/.exec(source);
    if(!start || !finish || finish.index < start.index)throw new Error('A secondary LaTeX document is missing its document boundaries. Close it before combining.');
    // Keep one document class, retain additional declarations, and include each
    // secondary body once. This changes the assembled view, never source cells.
    const extraPreamble = source.slice(0,start.index).replace(/\\documentclass(?:\[[^\]]*\])?\{[^}]*\}/g,'');
    for(const line of declarations(extraPreamble)) {
      const trimmed=line.trim();
      if(!trimmed || knownLines.has(trimmed))continue;
      // The root owns page geometry and title metadata. Other declarations are
      // retained so equations/custom commands in the added body remain usable.
      if(/^\\(?:title|author|date|geometry|pagestyle)(?:\[|\{)/.test(trimmed))continue;
      if(/^\\usepackage(?:\[[^\]]*\])?\{geometry\}/.test(trimmed))continue;
      additions.push(line);knownLines.add(trimmed);
    }
    const body=source.slice(start.index+start[0].length,finish.index).replace(/\\maketitle\b/g,'');
    extras.push(body);
  }
  return preamble + '\n' + (additions.length ? additions.join('\n')+'\n' : '') + document.slice(begin.index,end.index) + '\n' + extras.join('\n\n') + '\n' + document.slice(end.index);
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
  const latexCells = cells.filter(cell => cell.type === 'latex' && cell.source.trim() && !cell.filePath);
  // A notebook can contain a complete document; do not let the empty starter
  // paper create a second document or hide the notebook's real content.
  const hasCellDocument = latexCells.some(cell => /^\s*\\documentclass(?:\[|\{)/m.test(cell.source));
  const fileSources = hasCellDocument ? sources.filter(file => {
    const body = /\\begin\{document\}([\s\S]*?)\\end\{document\}/.exec(file.source)?.[1];
    return body === undefined || body.replace(/(?<!\\)%[^\n]*/g, '').replace(/\\null\b/g, '').trim() !== '';
  }) : sources;
  const uniqueCells = latexCells.filter(cell => !fileSources.some(file => file.source.includes(cell.source.trim())));
  try { return notebookLatex([...fileSources, ...uniqueCells]) ?? '\\null'; }
  catch(error){throw new Error((error as Error).message.replace('notebook','paper').replace('LaTeX cells','LaTeX files'));}
}
