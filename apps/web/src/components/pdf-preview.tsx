"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import { LoaderCircle } from "lucide-react";
import { Button } from "./ui/button";

export function PdfPreview({
  id,
  initialPage = 1,
}: {
  id: string;
  initialPage?: number;
}) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(initialPage);
  const [zoom, setZoom] = useState(1);
  const [width, setWidth] = useState(600);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const container = useRef<HTMLDivElement>(null);
  const surface = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(200, Math.floor(entry.contentRect.width - 24))),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let loading:
      ReturnType<typeof import("pdfjs-dist").getDocument> | undefined;
    let live = true;
    async function open() {
      try {
        const lib = await import("pdfjs-dist");
        lib.GlobalWorkerOptions.workerSrc = "/pdf-assets/pdf.worker.min.mjs";
        const response = await fetch(`/api/documents/${id}/preview`, {
          credentials: "same-origin",
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok)
          throw new Error(
            "This PDF is unavailable. Refresh the document list or sign in again.",
          );
        loading = lib.getDocument({
          data: new Uint8Array(await response.arrayBuffer()),
          cMapUrl: "/pdf-assets/cmaps/",
          cMapPacked: true,
          standardFontDataUrl: "/pdf-assets/standard_fonts/",
          useWasm: false,
          enableXfa: false,
          disableFontFace: true,
          maxImageSize: 16_000_000,
          canvasMaxAreaInBytes: 32_000_000,
        });
        const document = await loading.promise;
        if (live) {
          setPdf(document);
          setPage(Math.max(1, Math.min(initialPage, document.numPages)));
        }
      } catch (err) {
        if (live && !controller.signal.aborted) {
          setError(
            err instanceof Error ? err.message : "Could not open this PDF.",
          );
          setBusy(false);
        }
      }
    }
    void open();
    return () => {
      live = false;
      controller.abort();
      void loading?.destroy().catch(() => {});
    };
  }, [id, initialPage]);

  useEffect(() => {
    if (!pdf || !surface.current) return;
    let render: RenderTask | undefined;
    let live = true;
    const canvas = document.createElement("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `PDF page ${page}`);
    surface.current.replaceChildren(canvas);
    async function draw() {
      setBusy(true);
      setError("");
      try {
        const sheet = await pdf!.getPage(page);
        if (!live) return;
        const natural = sheet.getViewport({ scale: 1 });
        if (
          ![natural.width, natural.height].every(
            (value) => Number.isFinite(value) && value > 0,
          )
        )
          throw new Error("This page has unsupported dimensions.");
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        const scale = Math.min(
          (Math.min(width, 850) / natural.width) * zoom,
          Math.sqrt(8_000_000 / (natural.width * natural.height)) / ratio,
          8192 / (Math.max(natural.width, natural.height) * ratio),
        );
        const viewport = sheet.getViewport({
          scale,
        });
        canvas.width = Math.ceil(viewport.width * ratio);
        canvas.height = Math.ceil(viewport.height * ratio);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        render = sheet.render({
          canvas,
          viewport,
          transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
          annotationMode: 0,
        });
        await render.promise;
        const content = await sheet.getTextContent();
        if (live) {
          setText(
            content.items
              .map((item) => ("str" in item ? item.str : ""))
              .join(" "),
          );
          setBusy(false);
        }
      } catch (err) {
        if (live) {
          setError(
            err instanceof Error ? err.message : "Could not render this page.",
          );
          setBusy(false);
        }
      }
    }
    void draw();
    return () => {
      live = false;
      render?.cancel();
    };
  }, [pdf, page, width, zoom]);

  return (
    <div className="pdf-preview">
      <div className="pdf-controls">
        <Button
          variant="secondary"
          size="small"
          disabled={!pdf || page === 1 || busy}
          onClick={() => setPage(page - 1)}
        >
          Previous page
        </Button>
        <span aria-live="polite">
          Page {page} of {pdf?.numPages || "…"}
        </span>
        <Button
          variant="secondary"
          size="small"
          disabled={!pdf || page === pdf.numPages || busy}
          onClick={() => setPage(page + 1)}
        >
          Next page
        </Button>
        <label>
          Zoom
          <select
            aria-label="PDF zoom"
            value={zoom}
            onChange={(event) => setZoom(Number(event.target.value))}
          >
            <option value={1}>Fit width</option>
            <option value={1.25}>125%</option>
            <option value={1.5}>150%</option>
            <option value={2}>200%</option>
          </select>
        </label>
      </div>
      {busy && (
        <p className="pdf-status" role="status">
          <LoaderCircle className="spin" size={16} />
          Rendering PDF page…
        </p>
      )}
      {error && (
        <p className="alert error" role="alert">
          {error}
        </p>
      )}
      <div ref={container} className="pdf-canvas-scroll">
        <div ref={surface} />
      </div>
      {text && (
        <details className="pdf-page-text">
          <summary>Page text</summary>
          <p>{text}</p>
        </details>
      )}
      <a
        className="button secondary small"
        href={`/api/documents/${id}/preview?download=true`}
        download
      >
        Download original PDF
      </a>
    </div>
  );
}
