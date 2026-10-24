import { useEffect, useRef, useState } from 'react';
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

GlobalWorkerOptions.workerSrc = workerUrl;

function PaperPage({ document, number, width }: { document: PDFDocumentProxy; number: number; width: number }) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');
  const [text, setText] = useState('');
  useEffect(() => {
    if (!width || !host.current) return;
    let cancelled = false;
    let renderTask: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | undefined;
    const canvas = window.document.createElement('canvas');
    const container = host.current;
    setError('');
    async function render() {
      try {
        const page = await document.getPage(number);
        if (cancelled) return;
        const viewport = page.getViewport({ scale: width / page.getViewport({ scale: 1 }).width });
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.ceil(viewport.width * ratio);
        canvas.height = Math.ceil(viewport.height * ratio);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        canvas.setAttribute('aria-hidden', 'true');
        container.replaceChildren(canvas);
        renderTask = page.render({ canvas, viewport, transform: [ratio, 0, 0, ratio, 0, 0] });
        await renderTask.promise;
        const content = await page.getTextContent();
        if (!cancelled) setText(content.items.map(item => 'str' in item ? item.str : '').join(' '));
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : 'Could not render this page.');
      }
    }
    void render();
    return () => { cancelled = true; renderTask?.cancel(); canvas.remove(); };
  }, [document, number, width]);
  return <section className="pdf-page" aria-label={`Page ${number}`}>
    <div ref={host}/>
    <p className="sr-only">{text}</p>
    {error && <p className="pdf-message" role="alert">{error}</p>}
  </section>;
}

export default function PdfPreview({ url, zoom }: { url: string; zoom: number }) {
  const host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let cancelled = false;
    setDocument(null); setError('');
    const task = getDocument({ url });
    task.promise.then(pdf => { if (!cancelled) setDocument(pdf); }).catch(reason => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : 'Unable to load PDF. Compile again.');
    });
    return () => { cancelled = true; void task.destroy(); };
  }, [url]);
  return <div ref={host} className="pdf-document" aria-label="Compiled research paper" aria-busy={!document && !error}>
    {error ? <p className="pdf-message" role="alert">Could not open the PDF. {error}</p> : !document ? <p className="pdf-message" role="status">Loading paper…</p> :
      Array.from({ length: document.numPages }, (_, i) => <PaperPage key={`${url}-${i}`} document={document} number={i + 1} width={Math.max(1, width * zoom / 100)}/>)}
  </div>;
}
