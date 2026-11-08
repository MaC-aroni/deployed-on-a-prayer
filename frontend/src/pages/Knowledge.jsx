import { useEffect, useState } from "react";
import { ArrowLeft, ExternalLink, Sparkles } from "lucide-react";
import { EmptyState } from "../components/Shell.jsx";
import { Pill } from "../components/StatusIcon.jsx";
import { api } from "../mac/api.js";
import Markdown from "../components/Markdown.jsx";
import { Link } from "../router.jsx";

// One knowledge-base page, shown in the console when there's no Confluence to link to (or
// before it's published). Pages MaC wrote itself say so, with their review ticket.

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
      <article className="card knowledge-page"><Markdown text={page.body} className="" /></article>
    </>
  );
}
