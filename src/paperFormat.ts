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
