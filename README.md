# PRE Compose

A simple research notebook with executable Python, JavaScript, LaTeX, and Markdown cells.

## Run

```sh
npm install
npm run dev
```

Open the printed localhost URL. **Leave Backend API URL empty** in Settings to use the built-in local runtime. `npm run preview` also includes the runtime after `npm run build`; hosting only `dist/` requires an external API.

Python uses `.venv/bin/python` when available, otherwise `python3`. To set up scientific packages on a fresh checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm run setup:latex
```

The current workspace already has the virtual environment and Tectonic installed. The LaTeX setup script downloads the pinned official Tectonic 0.17.0 release to `.runtime/bin/`; its first compilation downloads TeX support files. Other platforms can install [Tectonic](https://tectonic-typesetting.github.io/en-US/install.html) directly. Override executables with `PRE_PYTHON` and `PRE_TECTONIC` environment variables.

## Cells

- **Python:** Run code, print output, inspect the final expression, and display Matplotlib plots. Variables persist between Python cells. Project files are copied into the kernel's working directory; Python can import from the root and `src/`.
- **JavaScript:** Run standard JavaScript and `console.log` in a separate persistent Node VM context. The last expression is displayed; returned promises are awaited. Use `var` for bindings you want to redefine when rerunning cells. Browser DOM, Node imports, and top-level `await` are not provided.
- **LaTeX:** Compile the selected cell into a real PDF. Fragments get an article wrapper with `amsmath`, `amssymb`, and `graphicx`; complete documents are used unchanged. The preview's Compile button compiles `paper/main.tex` instead.
- **Markdown:** Click Render to display the text. Double-click the rendered cell or use its edit icon to edit it.

Change a cell's language with its dropdown. **Run all** runs cells from top to bottom and stops at the first error. **Stop** interrupts the active execution and clears both code kernels. **Restart** clears variables while keeping old outputs visible. Code execution times out after 30 seconds; LaTeX after 90 seconds. Python and JavaScript do not share variables. Kernel state lasts until the page session or dev server is restarted; saved outputs are not live variables.

The default examples run without external datasets. Existing saved notebooks are preserved; older demo cells that import `torch`, `DiffusionModel`, or nonexistent figures still need those dependencies and project assets. Add a new cell for a quick check:

```python
import numpy as np
import matplotlib.pyplot as plt
x = np.linspace(0, 6, 100)
plt.plot(x, np.sin(x))
plt.show()
```

## Workspace

Notebook is the default view. Paper opens LaTeX source. Preview and Ask AI open supporting panels; Tools contains Review, Experiment, Replicate, Iterate, and Defend.

Text files and cells autosave in browser localStorage. Plot images remain in memory to avoid filling browser storage. Export downloads a project JSON backup; the notebook menu downloads `.ipynb`. Mixed JavaScript/Python notebooks retain language metadata but need an appropriate Jupyter kernel to execute outside PRE. Binary uploads and project archive import are not implemented.

## Local execution model

This runtime is for trusted code on your own computer. Python executes with your user permissions; it is not a security sandbox. The server binds to loopback and rejects cross-origin execution requests. Do not expose this runtime as a public or multi-user service. A deployed service must supply isolated execution workers, authentication, and resource quotas.

Each page gets independent persistent Python and JavaScript processes. There are at most 16 sessions per server; restart the server to release unused page sessions. Runtime files and downloaded executables are ignored by Git. Source changes to imported Python modules require Restart because Python caches imports. File synchronization writes the supplied files but does not delete runtime-generated files. PDFs are retained in server memory (most recent 30); recompile after restarting the server.

## Backend API

An optional Settings URL routes requests to an external backend. Local execution needs no URL or API keys. External backends should allow the frontend origin through CORS. AI chat and research tools still require your team's AI backend.

All routes accept JSON POST:

| Route | Request | Response |
| --- | --- | --- |
| `/api/execute` | `{ sessionId, language: "python" or "javascript", code, files }` | `{ stdout, stderr, error?, images: [PNG data URLs], durationMs, executionCount }` |
| `/api/compile` | `{ sessionId, files, source? , entrypoint? }` | `{ pdfUrl, logs }` |
| `/api/runtime/reset` | `{ sessionId }` | `{ ok: true }` |
| `/api/chat` | `{ messages: [{role, text}], mode, context: {cells, files} }` | `{ message }` |
| `/api/tools/:mode` | `{ prompt, files, cells }` | `{ result }` |

Files are `{ path, content }`. `source` compiles an individual LaTeX cell; otherwise `entrypoint` defaults to `paper/main.tex`. Local PDF URLs are served by `/api/pdf/:id`. Local execution POSTs require `X-PRE-Runtime: 1`; the client adds it only for same-origin requests. HTTP errors return `{ error }`; user-code exceptions are returned within successful execution responses so stdout is preserved.

## Verify

```sh
npm test
PRE_TEST_PLOTS=1 PRE_TEST_LATEX=1 npm test
npm run build
```

The extended suite requires scientific Python packages and Tectonic. It verifies real plot/PDF generation in addition to state persistence, language isolation, errors, file imports, path traversal rejection, timeouts, and cancellation.
