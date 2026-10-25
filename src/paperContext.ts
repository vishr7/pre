import type { Cell, ProjectFile } from './api';

// Keep voice context limited to the active project's manuscript source. Do not
// pass arbitrary files (data, settings, credentials, or code) to an examiner.
export const MAX_PAPER_CONTEXT_CHARS = 18_000;

function safePath(path: string): boolean {
  return !!path && !path.startsWith('/') && !path.includes('\\') && !path.includes('\0') &&
    path.split('/').every(part => part !== '..' && part !== '.');
}

function normalizeInclude(parent: string, target: string): string | undefined {
  if (!target || target.startsWith('/') || target.includes('\\') || target.includes('\0')) return undefined;
  const parts = parent.split('/').slice(0, -1);
  for (const part of target.split('/')) {
    if (!part || part === '.') continue;
    if (part === '..') {
      if (!parts.length) return undefined;
      parts.pop();
    } else parts.push(part);
  }
  const path = parts.join('/') + (target.endsWith('.tex') ? '' : '.tex');
  return safePath(path) ? path : undefined;
}

function sourceFromProject(files: ProjectFile[], cells: Cell[]): string {
  const texFiles = files.filter(file => file.path.endsWith('.tex') && safePath(file.path));
  const byPath = new Map(texFiles.map(file => [file.path, file.content]));
  const documentRoots = texFiles.filter(file => /\\documentclass(?:\[|\{)/m.test(file.content));
  const root = ['main.tex', 'paper/main.tex'].find(path => documentRoots.some(file => file.path === path)) ??
    documentRoots[0]?.path ?? ['main.tex', 'paper/main.tex'].find(path => byPath.has(path)) ?? texFiles[0]?.path;
  const visited = new Set<string>();
  const expand = (path: string, stack = new Set<string>()): string => {
    if (stack.has(path)) throw new Error(`Circular LaTeX inclusion in ${path}.`);
    if (visited.has(path)) return '';
    const content = byPath.get(path);
    if (content === undefined) return '';
    visited.add(path);
    const nextStack = new Set(stack).add(path);
    return content.split('\n').map(line => {
      const commentIndex = line.search(/(?<!\\)%/);
      const code = commentIndex < 0 ? line : line.slice(0, commentIndex);
      const expanded = code.replace(/\\(input|include)\s*\{([^}]+)\}/g, (_match, _command: string, rawTarget: string) => {
        const target = rawTarget.trim();
        const resolved = normalizeInclude(path, target);
        const candidate = resolved && byPath.has(resolved) ? resolved :
          (normalizeInclude('root.tex', target) && byPath.has(normalizeInclude('root.tex', target)!) ? normalizeInclude('root.tex', target)! : undefined);
        if (!resolved) return `[Skipped unsafe LaTeX reference: ${target}]`;
        if (!candidate) return `[Missing LaTeX section: ${target}]`;
        return `\n${expand(candidate, nextStack)}\n`;
      });
      return expanded + (commentIndex < 0 ? '' : line.slice(commentIndex));
    }).join('\n');
  };
  if (root) return expand(root);

  // Notebook LaTeX cells are manuscript content when the project has no file root.
  return cells.filter(cell => cell.type === 'latex' && !cell.filePath && cell.source.trim())
    .map(cell => cell.source).join('\n\n');
}

function readableLatex(source: string): string {
  let text = source.replace(/(?<!\\)%[^\n]*/g, '');
  const metadata = [...text.matchAll(/\\(title|author|date)\{([^}]*)\}/g)].map(match => match[2]);
  const body = /\\begin\{document\}([\s\S]*?)\\end\{document\}/.exec(text);
  if (body) text = body[1];
  else text = text.replace(/\\documentclass(?:\[[^\]]*\])?\{[^}]*\}/g, '');
  text = text.replace(/\\begin\{abstract\}/g, '\nAbstract\n').replace(/\\end\{abstract\}/g, '\n');
  text = text.replace(/\\(section|subsection|subsubsection|chapter)\*?(?:\[[^\]]*\])?\{([^}]*)\}/g, '\n## $2\n');
  text = `${metadata.join('\n')}\n${text.replace(/\\(title|author|date)\{([^}]*)\}/g, ' ')}`;
  text = text.replace(/\\(textbf|textit|emph|underline|textrm|texttt|mbox|mathrm|mathbf)\{([^{}]*)\}/g, '$2');
  text = text.replace(/\\(cite|citep|citet|ref|eqref|label)\*?(?:\[[^\]]*\])?\{([^}]*)\}/g, '[$2]');
  text = text.replace(/\\(includegraphics|bibliography|bibliographystyle|usepackage|maketitle)\*?(?:\[[^\]]*\])?\{[^}]*\}/g, ' ');
  text = text.replace(/\\(begin|end)\{(equation\*?|align\*?|math|displaymath|tabular\*?|table\*?|figure\*?|itemize|enumerate|description|center|quote|quotation|verbatim|lstlisting)(?:\{[^}]*\})?\}/g, '\n');
  text = text.replace(/\\(item)\b(?:\[[^\]]*\])?/g, '\n• ');
  text = text.replace(/\\(newpage|clearpage|pagebreak|centering|small|large|noindent)\b/g, ' ');
  text = text.replace(/\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?/g, ' ')
    .replace(/[{}]/g, ' ').replace(/[ \t]+/g, ' ').replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n').trim();
  return text;
}

export function preparePaperContext(files: ProjectFile[], cells: Cell[], maxChars = MAX_PAPER_CONTEXT_CHARS): string {
  const fullText = readableLatex(sourceFromProject(files, cells));
  if (!fullText || fullText === '\\null') return '';
  if (fullText.length <= maxChars) return fullText;
  const marker = '\n\n[Paper context shortened; remaining content omitted.]';
  if (maxChars <= marker.length) return marker.slice(0, maxChars);
  const budget = maxChars - marker.length;
  const blocks = fullText.split(/(?=^## )/m);
  if (blocks.length === 1) return `${fullText.slice(0, budget).replace(/\s+\S*$/, '')}${marker}`;
  const score = (block: string) => {
    const heading = block.slice(0, 160).toLowerCase();
    if (/abstract|method|experiment|dataset|result|discussion|limitation|conclusion/.test(heading)) return 5;
    if (/question|hypothes|related work|introduction/.test(heading)) return 4;
    return 1;
  };
  const ranked = blocks.map((text, index) => ({ text, index, score: score(text) }));
  const weightTotal = ranked.reduce((sum, block) => sum + block.score, 0);
  let remaining = budget;
  const ordered = [...ranked].sort((a, b) => b.score - a.score || a.index - b.index);
  const allocations = new Map<number, number>();
  for (const block of ordered) {
    const share = Math.max(1, Math.floor(budget * block.score / weightTotal));
    const take = Math.min(block.text.length, share, remaining);
    allocations.set(block.index, take);
    remaining -= take;
  }
  // Use capacity left by short sections on longer high priority sections.
  for (const block of ordered) {
    if (remaining <= 0) break;
    const current = allocations.get(block.index) ?? 0;
    const extra = Math.min(block.text.length - current, remaining);
    allocations.set(block.index, current + extra);
    remaining -= extra;
  }
  const selected = new Map([...allocations].map(([index, length]) => {
    const content = blocks[index].slice(0, length);
    return [index, length < blocks[index].length ? content.replace(/\s+\S*$/, '') : content];
  }));
  const clipped = [...selected.entries()].sort(([a], [b]) => a - b).map(([, text]) => text).filter(Boolean).join('\n\n');
  return `${clipped}${marker}`;
}

export function voiceSessionOptions(signedUrl: string, paperContext: string) {
  return {
    signedUrl,
    connectionType: 'websocket' as const,
    dynamicVariables: { paper_context: paperContext },
  };
}

export function examinerSignedUrlPath(examiner: 'supportive' | 'critical'): string {
  return `/defend/signed-url?examiner=${encodeURIComponent(examiner)}`;
}
