import { ui, useUILanguage } from "../i18n/ui";
// REQ-WEB-009/021, ADR-003, INV-WEB-012: sanitized, contained report content.
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

export function Markdown({ children }: { children: string }) {
  useUILanguage();
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          table: ({ children: tableChildren }) => (
            <div
              className="markdown-table-scroll"
              role="region"
              aria-label={ui("Report table")}
              tabIndex={0}
            >
              <table>{tableChildren}</table>
            </div>
          ),
          a: ({ href, children: linkChildren }) => (
            <a href={href} rel="noopener noreferrer" target="_blank">
              {linkChildren}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
