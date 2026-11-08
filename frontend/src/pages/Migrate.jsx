import { useCallback, useEffect, useState } from "react";
import { BookOpen, GitBranch, GitPullRequest, Network, Sparkles, Users, Wand2 } from "lucide-react";
import { EmptyState, useAuth } from "../components/Shell.jsx";
import StatusIcon, { Pill } from "../components/StatusIcon.jsx";
import { api, fmtAgo, follow } from "../mac/api.js";
import { Link, navigate } from "../router.jsx";
import { cx } from "../lib.js";

// Build → Migrate: pick a service from the knowledge graph, let the Planner write its pipeline.

function Toast({ toast, onClose }) {
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(onClose, 8000);
    return () => clearTimeout(id);
  }, [toast, onClose]);
  if (!toast) return null;
  return (
    <div className={cx("toast", `tone-${toast.tone}`)} role="status" onClick={onClose}>
      {toast.text}
    </div>
  );
}

export default function Migrate() {
  const { locked } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(null); // service name being planned, or "ingest"
  const [withPr, setWithPr] = useState(false);
  const [ingest, setIngest] = useState(null); // { id, lines } while an ingest streams

  const load = useCallback(() => api.services().then((d) => (setData(d), setError(null))).catch(setError), []);
  useEffect(() => {
    load();
  }, [load]);

  const closeToast = useCallback(() => setToast(null), []);
  const fail = (e) => setToast({ tone: e.status === 409 ? "amber" : "red", text: e.detail ?? String(e) });

  async function startIngest() {
    setBusy("ingest");
    try {
      const run = await api.ingest();
      setIngest({ id: run.id, lines: [] });
      const evs = await api.events(run.id);
      setIngest({ id: run.id, lines: evs });
      follow(
        run.id,
        evs.at(-1)?.seq ?? 0,
        (ev) => setIngest((cur) => (cur && !cur.lines.some((l) => l.seq === ev.seq) ? { ...cur, lines: [...cur.lines, ev] } : cur)),
        () => {
          setIngest(null);
          setBusy(null);
          load();
        },
      );
    } catch (e) {
      fail(e);
      setBusy(null);
    }
  }

  async function migrate(service) {
    setBusy(service.name);
    try {
      const run = await api.plan({ service: service.name, pr: withPr });
      navigate(`/migrate/${run.id}`);
    } catch (e) {
      fail(e);
      setBusy(null);
    }
  }

  if (error) return <EmptyState title="Backend unreachable" body={error.detail} />;
  if (!data) return <EmptyState title="Loading…" />;

  return (
    <>
      <Toast toast={toast} onClose={closeToast} />
      <div className="page-head">
        <h1>Migrate a service</h1>
        <p className="muted">
          Pick a service. The Planner reads the company knowledge base, writes its migration.yaml, checks it against the validator until it passes, and hands it to the runner.
        </p>
      </div>

      {!data.ingested ? (
        <article className="card card-wide">
          <header className="card-head">
            <span className="avatar violet">
              <Network size={13} />
            </span>
            <div className="card-title">
              <strong>Knowledge graph not built yet</strong>
              <span className="muted">Nemotron reads the 14 Confluence pages once and extracts services, repos, teams, approvers and policies, each with its source.</span>
            </div>
          </header>
          {ingest ? (
            <pre className="log ingest-log">{ingest.lines.filter((l) => l.kind !== "step" || l.step === "knowledge").map((l) => l.message).join("\n") || "starting…"}</pre>
          ) : (
            <footer className="card-foot">
              <button className={cx("btn btn-primary", { hint: locked })} onClick={startIngest} disabled={busy === "ingest"}>
                <Sparkles size={14} /> Ingest knowledge base
              </button>
              <span className="muted small">about 14 model calls · or run `mise run mac ingest`</span>
            </footer>
          )}
        </article>
      ) : (
        <>
          <div className="toolbar">
            <span className="muted small">
              Knowledge graph updated {fmtAgo(data.graph_updated)} · {data.services.length} service{data.services.length === 1 ? "" : "s"}
            </span>
            <label className="toggle-row" style={{ marginLeft: "auto" }}>
              <span>Also open a PR in mac-migrations</span>
              <button type="button" role="switch" aria-checked={withPr} className={cx("toggle", { on: withPr })} onClick={() => setWithPr((v) => !v)}>
                <span className="toggle-knob" />
              </button>
            </label>
            <button className="btn" onClick={startIngest} disabled={busy === "ingest"} title="Read the knowledge base again">
              <BookOpen size={14} /> Re-ingest
            </button>
          </div>

          {ingest && <pre className="log ingest-log">{ingest.lines.filter((l) => l.kind === "log").map((l) => l.message).join("\n") || "starting…"}</pre>}

          <div className="cards">
            {data.services.map((svc) => (
              <article className="card service-card" key={svc.name}>
                <header className="card-head">
                  <StatusIcon status={svc.plans.length ? "succeeded" : "pending"} size={22} />
                  <div className="card-title">
                    <strong>{svc.name}</strong>
                    {svc.team && (
                      <span className="muted">
                        <Users size={12} /> {svc.team}
                      </span>
                    )}
                  </div>
                  {svc.plans.length > 0 && <Pill tone="violet">{svc.plans.length} plan{svc.plans.length === 1 ? "" : "s"}</Pill>}
                </header>
                {svc.description && <p className="card-body">{svc.description}</p>}
                <div className="repo-list">
                  {svc.repos.length === 0 && <span className="muted small">no repositories documented</span>}
                  {svc.repos.map((r) => (
                    <span className="stage-chip" key={r}>
                      <GitBranch size={11} /> {r.split("/").pop()}
                    </span>
                  ))}
                </div>
                <footer className="card-foot">
                  <button className={cx("btn btn-primary", { hint: locked })} onClick={() => migrate(svc)} disabled={busy === svc.name}>
                    <Wand2 size={14} /> {busy === svc.name ? "Starting…" : "Migrate to AWS"}
                  </button>
                  {withPr && (
                    <span className="muted small">
                      <GitPullRequest size={12} /> opens a PR
                    </span>
                  )}
                  {svc.plans.length > 0 && (
                    <Link to={`/plans/${svc.plans[0]}`} className="link small">
                      latest plan
                    </Link>
                  )}
                  {svc.approvers.length > 0 && <span className="muted small">approvers: {svc.approvers.join(", ")}</span>}
                </footer>
              </article>
            ))}
            {data.services.length === 0 && <EmptyState title="No services in the knowledge graph" body="The ingest found no service pages. Check demo-data/confluence." />}
          </div>
        </>
      )}
    </>
  );
}
