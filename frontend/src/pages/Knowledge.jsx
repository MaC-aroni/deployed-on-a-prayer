import { useEffect, useState } from "react";
import { ArrowLeft, Check, ExternalLink, Sparkles, X } from "lucide-react";
import { EmptyState, useAuth } from "../components/Shell.jsx";
import { fmtAgo } from "../mac/api.js";
import { cx } from "../lib.js";
import { Pill } from "../components/StatusIcon.jsx";
import { api } from "../mac/api.js";
import Markdown from "../components/Markdown.jsx";
import { Link } from "../router.jsx";

// One knowledge-base page, shown in the console when there's no Confluence to link to (or
// before it's published). Pages MaC wrote itself say so, with their review ticket.

export default function Knowledge({ pageId }) {
  const { locked } = useAuth();
  const [page, setPage] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(null); // "approved" | "rejected"
  const [err, setErr] = useState(null);
  useEffect(() => {
    api.knowledge(pageId).then(setPage).catch(setError);
  }, [pageId]);

  async function review(status) {
    setBusy(true);
    setErr(null);
    try {
      setPage(await api.reviewKnowledge(pageId, status));
      setConfirm(null);
    } catch (e) {
      setErr(e.detail ?? String(e));
    } finally {
      setBusy(false);
    }
  }

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
      {page.generated && page.review && (
        <section className={cx("review-bar", `is-${page.review.status}`)}>
          <div className="review-text">
            <strong>
              {page.review.status === "approved" ? "Reviewed" : page.review.status === "rejected" ? "Rejected" : "Review needed"}
            </strong>
            <span className="muted">
              {page.review.status === "pending"
                ? `MaC wrote this page from ${page.review.repo ?? "the repository"}. It counts as documentation once a person signs it off`
                : `${page.review.status} by ${page.review.reviewed_by === "jira" ? "Jira" : `@${page.review.reviewed_by ?? "someone"}`}${page.review.reviewed_at ? ` · ${fmtAgo(page.review.reviewed_at)}` : ""}${page.review.note ? ` · ${page.review.note}` : ""}`}
              {page.review.ticket ? (
                <>
                  {" · ticket "}
                  <a className="link mono" href={page.review.ticket_url ?? "#"} target="_blank" rel="noreferrer">
                    {page.review.ticket}
                  </a>
                  {page.review.status === "pending" && " (approving it in Jira works too)"}
                </>
              ) : (
                page.review.status === "pending" && " · no Jira ticket was raised, so the review happens here"
              )}
            </span>
            {err && <span className="small" style={{ color: "var(--bad)" }}>{err}</span>}
          </div>
          <div className="review-actions">
            {confirm ? (
              <>
                <span className="small">{confirm === "approved" ? "Approve this page as documentation?" : "Reject it? It stays a draft until Learn rewrites it."}</span>
                <button className={cx("btn", confirm === "approved" ? "btn-primary" : "btn-danger")} onClick={() => review(confirm)} disabled={busy}>
                  Yes, {confirm === "approved" ? "approve" : "reject"}
                </button>
                <button className="btn" onClick={() => setConfirm(null)}>
                  Cancel
                </button>
              </>
            ) : (
              <>
                {page.review.status !== "approved" && (
                  <button className={cx("btn btn-primary", { hint: locked })} onClick={() => setConfirm("approved")} disabled={busy}>
                    <Check size={14} /> Approve
                  </button>
                )}
                {page.review.status !== "rejected" && (
                  <button className={cx("btn", { hint: locked })} onClick={() => setConfirm("rejected")} disabled={busy}>
                    <X size={14} /> Reject
                  </button>
                )}
              </>
            )}
          </div>
        </section>
      )}
      <article className="card knowledge-page"><Markdown text={page.body} className="" /></article>
    </>
  );
}
