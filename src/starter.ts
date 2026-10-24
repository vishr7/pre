import { blankPaper } from './paperFormat';
import type { Cell, ProjectFile } from './api';

// Exact prior starter content is used only to migrate untouched demo entries.
const legacyCells: Cell[] = [
  { id: 'intro', type: 'markdown', source: '# Research notebook\nRun a cell with the play button. Python and JavaScript keep their variables between cells. Use Restart to start fresh.' },
  { id: 'code', type: 'python', source: 'scores = [0.82, 0.87, 0.91, 0.89]\nmean = sum(scores) / len(scores)\nprint(f"Mean score: {mean:.3f}")\nmean' },
  { id: 'javascript', type: 'javascript', source: 'var scores = [0.82, 0.87, 0.91, 0.89];\nconsole.log("Best score:", Math.max(...scores));' },
  { id: 'equation', type: 'latex', source: '\\section{Results}\nThe mean score is $0.8725$.\n\\[ \\bar{x} = \\frac{1}{n} \\sum_{i=1}^{n} x_i \\]' }
];
const legacyFiles: ProjectFile[] = [{ path: 'paper/main.tex', content: '\\documentclass{article}\n\\usepackage{graphicx}\n\\title{Robust 3D Vision with Diffusion Models}\n\\author{Alex Morgan \\and Sarah Miller}\n\\begin{document}\n\\maketitle\n\\begin{abstract}\nWe present a unified framework for robust 3D vision using diffusion models.\n\\end{abstract}\n\\section{Introduction}\nRecent advances in generative modeling have significantly improved 3D vision tasks.\n\\end{document}' }, { path: 'paper/references.bib', content: '@article{ho2020denoising,\n title={Denoising Diffusion Probabilistic Models},\n author={Ho, Jonathan and Jain, Ajay and Abbeel, Pieter},\n year={2020}\n}' }, { path: 'src/model.py', content: '# Add your model implementation here\n' }, { path: 'README.md', content: '# Robust 3D Vision\nResearch workspace for diffusion-based reconstruction.' }, { path: 'environment.yml', content: 'name: diff3d\ndependencies:\n  - python=3.10\n  - pytorch\n  - matplotlib' }];

legacyCells.push(
 { id: 'intro', type: 'markdown', source: '# 1. Introduction\nRecent advances in generative modeling have significantly improved 3D vision tasks, including reconstruction, novel view synthesis, and scene understanding. In this work, we propose a unified framework that leverages diffusion models for robust 3D scene representation learning.' },
 { id: 'figure', type: 'latex', source: '\\begin{figure}[t]\n    \\centering\n    \\includegraphics[width=0.8\\linewidth]{figures/architecture.pdf}\n    \\caption{Overview of our framework.}\n    \\label{fig:overview}\n\\end{figure}' },
 { id: 'code', type: 'python', source: 'import torch\nimport matplotlib.pyplot as plt\nfrom model import DiffusionModel\nfrom utils import load_dataset, evaluate\n\n# Load dataset and evaluate model\ndataset = load_dataset("shapenet", split="test")\nmodel = DiffusionModel.from_pretrained("pretrained/diff3d")\nmetrics = evaluate(model, dataset)\n\nfor k, v in metrics.items():\n    print(f"{k}: {v:.4f}")' },
 { id: 'results', type: 'markdown', source: '## 2. Experimental results\nWe evaluate our method on ShapeNet and compare against NeRF and Instant3D. Our approach consistently improves reconstruction quality across unseen viewpoints.' }
);

export const initialCells: Cell[] = [{ id: 'start', type: 'python', source: '' }];
export const initialFiles: ProjectFile[] = [{
 path: 'paper/main.tex',
 content: blankPaper,
}];
export function cleanStarterCells(cells: Cell[]): Cell[] {
 const kept = cells.filter(cell => !legacyCells.some(old => old.id === cell.id && old.type === cell.type && old.source === cell.source));
 return kept.length ? kept : initialCells;
}
export function cleanStarterFiles(files: ProjectFile[]): ProjectFile[] {
 return files.flatMap(file => {
   if (!legacyFiles.some(old => old.path === file.path && old.content === file.content)) return [file];
   return initialFiles.filter(replacement => replacement.path === file.path);
 });
}
