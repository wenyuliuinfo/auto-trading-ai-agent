import { ReactNode } from "react";

interface ReportViewProps {
  markdown: string;
}

function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderInline(text: string): ReactNode[] {
  const escaped = escapeHtml(text);
  const parts = escaped.split(/(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|\*[^*]+\*)/g);
  return parts.map((part, index) => {
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) {
      return (
        <a
          key={index}
          href={link[2]}
          target="_blank"
          rel="noopener noreferrer"
          className="report-link"
        >
          {link[1]}
        </a>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return <em key={index}>{part.slice(1, -1)}</em>;
    }
    return <span key={index}>{part}</span>;
  });
}

export function ReportView({ markdown }: ReportViewProps) {
  const lines = markdown.split("\n");
  const nodes: ReactNode[] = [];
  let paragraph: string[] = [];
  let key = 0;
  const headingTags = {
    1: "h1",
    2: "h2",
    3: "h3",
    4: "h4",
    5: "h5",
    6: "h6",
  } as const;

  function flushParagraph() {
    if (paragraph.length > 0) {
      nodes.push(<p key={key++}>{renderInline(paragraph.join(" "))}</p>);
      paragraph = [];
    }
  }

  for (const line of lines) {
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushParagraph();
      const level = Math.min(heading[1].length, 6) as 1 | 2 | 3 | 4 | 5 | 6;
      const HeadingTag = headingTags[level];
      nodes.push(<HeadingTag key={key++}>{renderInline(heading[2])}</HeadingTag>);
    } else if (line.startsWith("- ")) {
      flushParagraph();
      nodes.push(
        <ul key={key++} style={{ margin: "0.35rem 0" }}>
          <li>{renderInline(line.slice(2))}</li>
        </ul>,
      );
    } else if (line.startsWith("---")) {
      flushParagraph();
      nodes.push(<hr key={key++} className="report-hr" />);
    } else if (line.trim() === "") {
      flushParagraph();
    } else {
      paragraph.push(line);
    }
  }
  flushParagraph();

  return <div className="report-md">{nodes}</div>;
}
