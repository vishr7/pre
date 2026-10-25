import type { ProjectFile } from './api';
import type { UploadedFigure } from './figureAssets';

// What each kind of paper file is for, shown when hovering over it in the file panel.
const kinds: [RegExp, string][] = [
  [/(^|\/)main\.tex$/i, 'Main paper: the document that pulls in every other file'],
  [/\.tex$/i, 'LaTeX section: part of the paper, pulled in by the main file with \\input'],
  [/\.bib$/i, 'Reference database: the papers this work cites (authors, titles, years)'],
  [/\.bst$/i, 'Reference style: how citations and the reference list are formatted'],
  [/\.bbl$/i, 'Pre-built reference list, generated from the .bib and .bst files'],
  [/\.sty$/i, 'Style package: formatting rules such as fonts, margins, and headers'],
  [/\.(cls|clo)$/i, 'Document class: a full template for the paper layout'],
  [/\.(png|jpe?g|pdf)$/i, 'Figure: an image or plot included in the paper'],
];
export function describeFile(path: string): string | undefined {
  return kinds.find(([pattern]) => pattern.test(path))?.[1];
}
export const folderDescriptions: Record<string, string> = {
  sections: 'Parts of the paper that the main file pulls in',
  figures: 'Images and plots used in the paper',
  bibliography: 'References: .bib database, .bst style, and pre-built .bbl list',
  styles: 'Formatting templates: .sty packages and .cls classes',
};

const isDocument = (file: ProjectFile) => file.path.endsWith('.tex') && /^\s*\\documentclass(?:\[|\{)/m.test(file.content);
const withoutTex = (path: string) => path.replace(/\.tex$/i, '');

// Sorts an unzipped arXiv folder into main.tex, sections/, figures/, bibliography/, and styles/,
// rewriting \input paths and adding \graphicspath so the paper still compiles after the move.
export function organizePaperFolder(texts: ProjectFile[], images: UploadedFigure[], mainPath = 'main.tex') {
  const documents = texts.filter(isDocument);
  const main = documents.find(f => /(^|\/)(main|ms|paper)\.tex$/i.test(f.path)) || documents[0];
  const moved = new Map<string, string>();
  const place = (path: string): string => {
    if (main && path === main.path) return mainPath;
    const name = path.split('/').pop()!;
    if (/\.(bib|bbl|bst)$/i.test(path)) return `bibliography/${name}`;
    if (/\.(sty|cls|clo)$/i.test(path)) return `styles/${name}`;
    if (/\.tex$/i.test(path)) return path.startsWith('sections/') ? path : `sections/${path}`;
    return path;
  };
  for (const file of texts) moved.set(file.path, place(file.path));
  // \input{intro} or \include{chapters/intro} now point at sections/...; only .tex moves change these references.
  const retarget = (content: string) => content.replace(/\\(input|include)\s*\{([^}]+)\}/g, (original, command: string, target: string) => {
    const source = target.endsWith('.tex') ? target : `${target}.tex`;
    const destination = moved.get(source);
    if (!destination || destination === source || destination === mainPath) return original;
    return `\\${command}{${target.endsWith('.tex') ? destination : withoutTex(destination)}}`;
  });
  const files = texts.map(file => ({ path: moved.get(file.path)!, content: /\.tex$/i.test(file.path) ? retarget(file.content) : file.content }));
  const figures = images.map(image => ({ ...image, path: image.path.startsWith('figures/') ? image.path : `figures/${image.path}` }));
  const paper = main ? files.find(f => f.path === mainPath) : undefined;
  if (paper && figures.length) paper.content = addFiguresPath(paper.content);
  return { files, figures, main: main?.path };
}
// Lets \includegraphics{plot} find figures/plot.pdf; existing \graphicspath folders are kept under figures/.
export function addFiguresPath(content: string): string {
  const existing = /\\graphicspath\s*\{((?:\{[^}]*\})+)\}/.exec(content);
  if (existing) {
    const folders = [...existing[1].matchAll(/\{([^}]*)\}/g)].map(m => m[1]);
    const all = [...new Set([...folders.map(f => f.startsWith('figures/') ? f : `figures/${f.replace(/^\.\//, '')}`), 'figures/', ...folders])];
    return content.replace(existing[0], `\\graphicspath{${all.map(f => `{${f}}`).join('')}}`);
  }
  if (!/\\usepackage(\[[^\]]*\])?\{[^}]*\bgraphicx?\b[^}]*\}/.test(content)) return content;
  return content.replace(/\\begin\{document\}/, '\\graphicspath{{figures/}}\n\\begin{document}');
}
