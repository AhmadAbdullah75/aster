"use client";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Check, Copy } from "lucide-react";
import { Button } from "./ui/button";
function Code({ children }: { children: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="code-wrap" dir="ltr">
      <Button
        size="small"
        variant="secondary"
        className="copy-code"
        aria-label="Copy code"
        onClick={async (e) => {
          const code =
            e.currentTarget.parentElement?.querySelector("pre")?.textContent ||
            "";
          await navigator.clipboard.writeText(code);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
        {copied ? "Copied" : "Copy"}
      </Button>
      <pre>{children}</pre>
    </div>
  );
}
export function Markdown({
  text,
  onSource,
  allowedSources,
  allowedUrls,
}: {
  text: string;
  onSource?: (id: string) => void;
  allowedSources?: string[];
  allowedUrls?: string[];
}) {
  const formatted = text
    .replace(
      /\[url:\s*(https?:\/\/[^\]\s]+)\s*\]/gi,
      (original, url: string) =>
        allowedUrls?.includes(url) ? `[Source ↗](${url})` : original,
    )
    .replace(/\[source:([a-f0-9-]{36})\]/g, (_, id: string) =>
      !allowedSources || allowedSources.includes(id)
        ? `[${id}](#source-${id})`
        : "[source unavailable]",
    );
  return (
    <div className="markdown" dir="auto">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[
          rehypeHighlight,
          [rehypeKatex, { trust: false, strict: "ignore", maxExpand: 1000 }],
        ]}
        components={{
          pre: ({ children }) => <Code>{children}</Code>,
          a: ({ href, children }) =>
            href?.startsWith("#source-") ? (
              <button
                className="citation"
                onClick={() => onSource?.(href.slice(8))}
              >
                Source ↗
              </button>
            ) : (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ),
          img: ({ alt }) => <span className="muted">[Image: {alt}]</span>,
        }}
      >
        {formatted}
      </ReactMarkdown>
    </div>
  );
}
