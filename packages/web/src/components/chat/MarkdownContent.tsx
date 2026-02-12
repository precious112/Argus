"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

interface MarkdownContentProps {
  content: string;
}

const components: Components = {
  pre({ children }) {
    return (
      <pre className="overflow-x-auto rounded-md bg-[#0d1117] p-3">
        {children}
      </pre>
    );
  },
  code({ className, children, ...props }) {
    const isBlock = className?.startsWith("language-");
    if (isBlock) {
      return (
        <code className={`${className} text-xs`} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code
        className="rounded bg-[var(--background)] px-1 py-0.5 text-xs"
        {...props}
      >
        {children}
      </code>
    );
  },
  a({ href, children, ...props }) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-argus-400 underline"
        {...props}
      >
        {children}
      </a>
    );
  },
  table({ children }) {
    return (
      <div className="overflow-x-auto">
        <table className="w-full border-collapse border border-[var(--border)] text-xs">
          {children}
        </table>
      </div>
    );
  },
  th({ children }) {
    return (
      <th className="border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-left text-[var(--muted)]">
        {children}
      </th>
    );
  },
  td({ children }) {
    return (
      <td className="border border-[var(--border)] px-2 py-1">
        {children}
      </td>
    );
  },
};

export function MarkdownContent({ content }: MarkdownContentProps) {
  if (!content) return null;

  return (
    <div className="prose prose-sm prose-invert max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
