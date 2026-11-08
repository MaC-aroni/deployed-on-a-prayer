import { useEffect, useState } from "react";
import { ArrowLeft, ExternalLink, Sparkles } from "lucide-react";
import { EmptyState } from "../components/Shell.jsx";
import { Pill } from "../components/StatusIcon.jsx";
import { api } from "../mac/api.js";
import { Link } from "../router.jsx";

// One knowledge-base page, shown in the console when there's no Confluence to link to (or
// before it's published). Pages MaC wrote itself say so, with their review ticket.

function render(md) {
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

export default function Knowledge({ pageId }) {
  const [page, setPage] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    api.knowledge(pageId).then(setPage).catch(setError);
  }, [pageId]);

  if (error) return <EmptyState title="No such page" body={error.detail ?? String(error)} />;
  if (!page) return <EmptyState title="Loading…" />;

  return (
    <>
      <div className="run-head">
        <div className="run-head-main">
          <div className="run-meta" style={{ marginBottom: 6 }}>
            {page.generated ? (
              <Pill tone="violet">
                <Sparkles size={11} /> written by MaC
              </Pill>
            ) : (
              <Pill tone="grey">knowledge base</Pill>
            )}
            {page.labels.map((l) => (
              <span key={l} className="stage-chip">
                {l}
              </span>
            ))}
          </div>
          <h1>{page.title}</h1>
          <div className="run-meta">
            {page.owner && <span>owner {page.owner}</span>}
            <span className="mono">{page.id}</span>
            {page.review?.ticket && (
              <a className="link mono" href={page.review.ticket_url ?? "#"} target="_blank" rel="noreferrer">
                review {page.review.ticket} <ExternalLink size={11} />
              </a>
            )}
            {page.review?.repo && <span>from {page.review.repo}</span>}
          </div>
        </div>
        <div className="run-actions">
          <div className="actions-row">
            <Link to="/migrate" className="btn">
              <ArrowLeft size={14} /> Migration
            </Link>
            {page.url && (
              <a className="btn btn-primary" href={page.url} target="_blank" rel="noreferrer">
                Open in Confluence <ExternalLink size={12} />
              </a>
            )}
          </div>
        </div>
      </div>
      <article className="card knowledge-page">{render(page.body)}</article>
    </>
  );
}
