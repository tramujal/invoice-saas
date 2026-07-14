"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// No @tailwindcss/typography plugin in this project (and no other markdown
// rendering exists to reuse) — rather than adding another dependency just
// for "prose" styling, element-level classes are applied directly here.
// react-markdown never renders raw HTML by default (no rehype-raw plugin
// is used), so this stays safe regardless of what the model outputs.
const markdownComponents: Components = {
  p: ({ children }) => <p className="my-1.5 leading-relaxed first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5">{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer" className="underline">
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="rounded bg-slate-200/70 px-1 py-0.5 text-xs">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-lg bg-slate-800 p-3 text-xs text-slate-100">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="px-2 py-1 text-left font-semibold text-slate-700">{children}</th>
  ),
  td: ({ children }) => <td className="px-2 py-1">{children}</td>,
};

/** Isolated into its own module so the assistant page can `next/dynamic`
 * this in — react-markdown + remark-gfm are only ever used here, on the
 * one route that renders assistant replies. */
export function MarkdownMessage({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {content}
    </ReactMarkdown>
  );
}
