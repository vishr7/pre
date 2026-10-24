# PRE Compose

A pearl-white and muted rose research IDE built with React, TypeScript, Vite, and locally bundled Monaco Editor.

## Start

```sh
npm install
npm run dev
```

Open the local URL printed by Vite. `npm run build` type-checks and produces `dist/`; `npm run preview` serves that build.

## Workspace

The notebook is the default view. Use **Paper** to edit LaTeX, **Preview** to show or hide the PDF panel, **Ask AI** to open chat, and **Tools** for the research workflows.

- Notebook cells support Python, LaTeX, and rendered Markdown. Click the edit icon or double-click Markdown to edit; Run returns it to rendered mode.
- Add, edit, delete, and upload text files through Explorer. Files and notebook cells automatically persist in browser localStorage.
- Export creates a complete project JSON backup. The notebook's ellipsis button exports a Jupyter-compatible `.ipynb` (LaTeX cells are Markdown with `metadata.pre_type`). Individual files can be downloaded from the file editor.
- Compile displays the PDF returned by your LaTeX service. Run or Run all executes Python cells sequentially through the execution API.
- Chat includes project context. Review, Experiment, Replicate, Iterate, and Defend provide dedicated prompt/result workspaces.
- PDF compilation, Python execution, and AI require the backend services below. The preview stays empty until compilation succeeds. Python runs on your team's backend.

## Backend contract

Set the API base URL in **Workspace settings** (e.g. `http://localhost:8000`). Requests use JSON POST with a 120-second timeout. Configure backend CORS to allow the frontend's origin. Relative base paths such as `/backend` are supported. The frontend does not include a backend or API keys.

### `POST /api/compile`

Request: `{ files: [{ path, content }], cells: [{ id, type, source, output? }], entrypoint: "paper/main.tex" }`

Response: `{ pdfUrl: string, logs?: string }`. Return a browser-accessible absolute URL or same-origin URL that permits iframe display. The backend decides how notebook LaTeX cells are assembled with project files; the main entrypoint is supplied explicitly. The PDF appears after a successful compile.

### `POST /api/execute`

Request: `{ code: string, language: "python", files: [{ path, content }] }`

Response: `{ stdout: string, error?: string }`. Return textual output; graphical output transport is a future API extension. The backend must provide isolated execution and execution limits. Run all sends Python cells in order; kernel/session persistence is the backend's responsibility.

### `POST /api/chat`

Request: `{ messages: [{ role: "user" | "assistant", text: string }], mode: string, context: { cells, files } }`

Response: `{ message: string }` (Markdown supported).

### `POST /api/tools/:mode`

Modes: `review`, `experiment`, `replicate`, `iterate`, `defend`.

Request: `{ prompt: string, files, cells }`

Response: `{ result: string }` (Markdown supported).

Non-2xx responses are surfaced in the interface. API responses are expected to match these contracts. There is no authentication or collaborative editing layer yet; connect these through the team's API architecture before multi-user deployment.

## Scope and persistence

Local text uploads include `.tex`, `.bib`, `.sty`, `.py`, `.md`, `.txt`, `.csv`, `.tsv`, `.json`, and YAML. Binary assets and dataset storage belong on the backend. LocalStorage is browser-specific and size-limited; export important work. Project JSON import, persistent kernel identifiers, collaborative editing, and streaming AI responses are not implemented.
