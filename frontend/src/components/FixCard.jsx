import { ExternalLink, GitPullRequest, ShieldCheck } from "lucide-react";
import { Pill } from "./StatusIcon.jsx";
import { cx } from "../lib.js";

// What the Diagnostician found on a failed run, and the one manual command: approve the fix.
// `run` is a diagnose run (docs/planning-api.md); approving opens the fix as a pull request.
export default function FixCard({ run, onApprove, busy, locked }) {
  const rep = run?.report ?? {};
  if (!run || run.mode !== "diagnose") return null;
  const done = run.status === "succeeded";
  return (
    <article className="card fix-card">
      <header className="card-head">
        <div className="card-title">
          <strong>
            {done ? "Root cause" : run.status === "failed" ? "Investigation failed" : "Investigating…"} <span className="mono muted">{rep.step ?? run.failed_step}</span>
          </strong>
          <span className="muted">
            {rep.repo} {rep.sha ? `@ ${rep.sha.slice(0, 7)}` : ""} {rep.confidence ? `· ${rep.confidence} confidence` : ""}
          </span>
        </div>
        {rep.pr_url ? (
          <Pill tone="green">fix approved</Pill>
        ) : done ? (
          <Pill tone="amber">awaiting approval</Pill>
        ) : (
          <Pill tone={run.status === "failed" ? "red" : "violet"}>{run.status === "failed" ? "failed" : "running"}</Pill>
        )}
      </header>
      {done && (
        <>
          <p className="card-body">{rep.root_cause}</p>
          <p className="card-body">
            <strong>Fix:</strong> {rep.fix}
          </p>
          {rep.files?.length > 0 && (
            <div className="repo-list">
              {rep.files.map((f) => (
                <span className="stage-chip mono" key={f}>
                  {f}
                </span>
              ))}
            </div>
          )}
        </>
      )}
      {run.status === "failed" && <p className="card-body">{run.reason}</p>}
      <footer className="card-foot">
        {rep.ticket && (
          <a className="link mono" href={rep.ticket_url ?? "#"} target="_blank" rel="noreferrer">
            {rep.ticket} <ExternalLink size={11} />
          </a>
        )}
        {done && !rep.ticket && <span className="muted small">no Jira configured: approve here</span>}
        <span className="spacer" />
        {rep.pr_url ? (
          <a className="btn" href={rep.pr_url} target="_blank" rel="noreferrer">
            <GitPullRequest size={14} /> Fix pull request <ExternalLink size={11} />
          </a>
        ) : (
          done &&
          onApprove && (
            <button className={cx("btn btn-primary", { hint: locked })} onClick={onApprove} disabled={busy || rep.files?.length === 0} title={rep.files?.length === 0 ? "No code change was proposed" : "Open the fix as a pull request"}>
              <ShieldCheck size={14} /> Approve fix
            </button>
          )
        )}
      </footer>
    </article>
  );
}
