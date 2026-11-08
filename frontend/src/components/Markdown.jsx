// A small Markdown renderer for the text the agents write (knowledge pages, diagnoses):
// headings, lists, paragraphs, fenced code, inline code/bold/italic/links. No dependency.

export function render(md) {
  const out = [];
  let list = null;
  let code = null;
  const flush = () => {
    if (list) out.push(<ul key={out.length}>{list}</ul>);
    list = null;
  };
  md.split("\n").forEach((raw, i) => {
    const line = raw.replace(/\r$/, "");
    if (code !== null) {
      if (line.startsWith("```")) {
        out.push(<pre key={i} className="log yaml">{code.join("\n")}</pre>);
        code = null;
      } else code.push(line);
      return;
    }
    if (line.startsWith("```")) return void (flush(), (code = []));
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) return void (flush(), out.push(h[1].length <= 2 ? <h2 key={i}>{h[2]}</h2> : <h3 key={i}>{h[2]}</h3>));
    const li = /^\s*[-*]\s+(.*)$/.exec(line);
    if (li) return void (list ??= []).push(<li key={i}>{inline(li[1])}</li>);
    if (!line.trim()) return flush();
    if (line.startsWith("|")) return void (flush(), out.push(<p key={i} className="mono small">{line}</p>));
    flush();
    out.push(<p key={i}>{inline(line)}</p>);
  });
  flush();
  return out;
}

function inline(text) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|_[^_]+_|https?:\/\/\S+)/g);
  return parts.map((p, i) => {
    if (p.startsWith("`")) return <code key={i}>{p.slice(1, -1)}</code>;
    if (p.startsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("_") && p.endsWith("_") && p.length > 2) return <em key={i}>{p.slice(1, -1)}</em>;
    if (/^https?:\/\//.test(p)) {
      const clean = p.replace(/[).,]+$/, "");
      return (
        <a key={i} href={clean} target="_blank" rel="noreferrer" className="link">
          {clean}
        </a>
      );
    }
    return p;
  });
}

export default function Markdown({ text, className }) {
  if (!text) return null;
  return <div className={className ?? "markdown"}>{render(text)}</div>;
}
