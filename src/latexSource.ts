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
