// Shared by new projects and fragment compilation so both use the same layout.
export const paperPreamble = String.raw`\documentclass[11pt,letterpaper]{article}
\usepackage[margin=1in]{geometry}
\usepackage{amsmath,amssymb,graphicx}
\usepackage{booktabs,tabularx}
\setlength{\parindent}{1.5em}
\setlength{\parskip}{0pt}
\linespread{1.05}
\setlength{\emergencystretch}{2em}
\widowpenalty=10000
\clubpenalty=10000
\pagestyle{plain}`;
export function formatPaper(source: string): string {
 if (/^\s*\\documentclass(?:\[|\{)/m.test(source)) return source;
 return `${paperPreamble}\n\\begin{document}\n${source.trim() || '\\null'}\n\\end{document}\n`;
}
export const blankPaper = formatPaper('\\null\n% Write your paper here.\n');

// Measure ordinary table contents and shrink only when wider than the current
// column. Captions stay normal size. Source files remain editable and unchanged.
export function fitWideTables(source:string):string {
 let changed=false;
 const document=source.replace(/\\begin\{(?:verbatim|lstlisting|minted)\}[\s\S]*?\\end\{(?:verbatim|lstlisting|minted)\}|(?<!\\)%[^\n]*|\\begin\{table\*?\}[\s\S]*?\\end\{table\*?\}/g,block=>{
  if(!block.startsWith('\\begin{table'))return block;
  if(/\\(?:resizebox|scalebox)|\\begin\{(?:adjustbox|tabularx|longtable)\}/.test(block))return block;
  return block.replace(/\\begin\{tabular\}(?:\[[^\]]*\])?\{[^\n]*?\}[\s\S]*?\\end\{tabular\}/g,table=>{
   if((table.match(/\\begin\{tabular\}/g)||[]).length!==1)return table;
   changed=true;
   return '\\begingroup\\setbox0=\\hbox{'+table+'}\\ifdim\\wd0>\\linewidth\\resizebox{\\linewidth}{!}{\\box0}\\else\\box0\\fi\\endgroup';
  });
 });
 return changed?document.replace(/\\begin\{document\}/,'\\RequirePackage{graphicx}\n\\begin{document}'):source;
}
