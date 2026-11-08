import { useCallback, useEffect, useMemo, useState } from "react";
import { BookOpen, ExternalLink, GitBranch, Sparkles, Wand2 } from "lucide-react";
import Menu from "../components/Menu.jsx";
import { EmptyState, useAuth } from "../components/Shell.jsx";
import StatusIcon, { Pill } from "../components/StatusIcon.jsx";
import { api, fmtAgo, follow } from "../mac/api.js";
import { Link, navigate } from "../router.jsx";
import { runMeta } from "../status.js";
import { cx } from "../lib.js";

// Build → Migrate. Every candidate shows first: the services the knowledge base documents, and
// every repository in the org. Per service the steps are Learn (Nemotron reads the knowledge
// base into a graph) → Plan (Nemotron writes migration.yaml against the validator) → Build.

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

function Step({ label, status, text }) {
  return (
    <span className={cx("step-dot", `tone-${status}`)}>
      <span className="step-dot-mark" />
      <span className="step-dot-label">{label}</span>
      {text && <span className="step-dot-text">{text}</span>}
    </span>
  );
}

export default function Migrate() {
  const { locked } = useAuth();
  const [data, setData] = useState(null);
  const [plans, setPlans] = useState([]);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(null); // service name, or "ingest"
  const [withPr, setWithPr] = useState(false);
  const [ingest, setIngest] = useState(null); // { id, lines } while a Learn streams

  const load = useCallback(
    () =>
      Promise.all([api.services(), api.plans().catch(() => [])])
        .then(([d, p]) => {
          setData(d);
          setPlans(p);
          setError(null);
        })
        .catch(setError),
    [],
  );
  useEffect(() => {
    load();
  }, [load]);

  const closeToast = useCallback(() => setToast(null), []);
  const fail = (e) => setToast({ tone: e.status === 409 ? "amber" : e.status === 401 ? "blue" : "red", text: e.detail ?? String(e) });

  async function learn() {
    setBusy("ingest");
    try {
      const run = await api.ingest();
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

  async function plan(service) {
    setBusy(service.name);
    try {
      const run = await api.plan({ service: service.name, pr: withPr });
      navigate(`/migrate/${run.id}`);
    } catch (e) {
      fail(e);
      setBusy(null);
    }
  }

  const planById = useMemo(() => Object.fromEntries(plans.map((p) => [p.run_id, p])), [plans]);

  if (error) return <EmptyState title="Backend unreachable" body={error.detail} />;
  if (!data) return <EmptyState title="Loading…" />;

  const learnedLine = data.ingested ? `learned ${fmtAgo(data.graph_updated)}` : "not learned yet";

  return (
    <>
      <Toast toast={toast} onClose={closeToast} />

      <div className="page-head">
        <h1>Migrate a service</h1>
        <p className="muted">
          Knowledge base · {data.knowledge.pages} pages · {learnedLine}. Nemotron learns it into a graph, plans the migration.yaml against the validator, and the runner builds it.
        </p>
      </div>

      {ingest && <pre className="log ingest-log">{ingest.lines.filter((l) => l.kind === "log" || l.step === "knowledge").map((l) => l.message).join("\n") || "starting…"}</pre>}

      <div className="toolbar">
        <span className="label">Services in the knowledge base</span>
        <span className="spacer" />
        <label className="toggle-row">
          <span>Also open a PR</span>
          <button type="button" role="switch" aria-checked={withPr} className={cx("toggle", { on: withPr })} onClick={() => setWithPr((v) => !v)}>
            <span className="toggle-knob" />
          </button>
        </label>
        <button className={cx("btn", { hint: locked })} onClick={learn} disabled={busy === "ingest"} title="Read the knowledge base into the graph without planning">
          <BookOpen size={14} /> {data.ingested ? "Re-learn" : "Learn only"}
        </button>
      </div>

      <div className="cards">
        {data.services.map((svc) => {
          const latestPlanId = svc.plans[0];
          const latestPlan = latestPlanId ? planById[latestPlanId] : null;
          const build = latestPlan?.latest?.build;
          const learnStatus = svc.learned ? "green" : "grey";
          const planStatus = latestPlanId ? "green" : "grey";
          const buildMeta = build ? runMeta(build.status, "build") : null;
          const primary = latestPlanId
            ? { label: "Open pipeline", onClick: () => navigate(`/plans/${latestPlanId}`), icon: <Wand2 size={14} /> }
            : { label: svc.learned ? "Plan with Nemotron" : "Learn & plan", onClick: () => plan(svc), icon: <Sparkles size={14} /> };
          return (
            <article className="card service-card" key={svc.name}>
              <header className="card-head">
                <div className="card-title">
                  <strong>{svc.name}</strong>
                  <span className="muted">{svc.team ?? "owner unknown"}</span>
                </div>
                <Menu
                  label={`More for ${svc.name}`}
                  items={[
                    { label: svc.learned ? "Re-learn knowledge base" : "Learn only", detail: "ingest, no plan", icon: <BookOpen size={14} />, onClick: learn },
                    { label: latestPlanId ? "Plan again" : "Plan with Nemotron", detail: withPr ? "opens a PR too" : "writes migration.yaml", icon: <Sparkles size={14} />, onClick: () => plan(svc) },
                    ...(svc.plans.length > 1 ? svc.plans.slice(1, 4).map((id) => ({ label: `Open plan ${id}`, onClick: () => navigate(`/plans/${id}`) })) : []),
                  ]}
                />
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
              <div className="stepper">
                <Step label="Learn" status={learnStatus} text={svc.learned ? "graph ready" : "knowledge base"} />
                <Step label="Plan" status={planStatus} text={latestPlan ? `${latestPlan.iterations ?? "?"} attempt${latestPlan.iterations === 1 ? "" : "s"}` : "Nemotron"} />
                <Step label="Build" status={buildMeta ? buildMeta.tone : "grey"} text={buildMeta ? buildMeta.label.toLowerCase() : "runner"} />
              </div>
              <footer className="card-foot">
                <button className={cx("btn btn-primary", { hint: locked })} onClick={primary.onClick} disabled={busy === svc.name || busy === "ingest"}>
                  {primary.icon} {busy === svc.name ? "Starting…" : primary.label}
                </button>
                {svc.approvers.length > 0 && <span className="muted small">approvers: {svc.approvers.join(", ")}</span>}
                {svc.plans.length > 0 && (
                  <span className="muted small">
                    {svc.plans.length} plan{svc.plans.length === 1 ? "" : "s"}
                  </span>
                )}
              </footer>
            </article>
          );
        })}
        {data.services.length === 0 && <EmptyState title="No services in the knowledge base" body="No page carries the `service` label. Check demo-data/confluence." />}
      </div>

      <div className="toolbar" style={{ marginTop: 32 }}>
        <span className="label">Repositories in the organisation</span>
        <span className="spacer" />
        <span className="muted small">{data.repos.length} repositories · the Planner only uses documented ones</span>
      </div>
      {data.repos_error && <p className="muted small">{data.repos_error}</p>}
      {data.repos.length > 0 && (
        <div className="table repos-table">
          {data.repos.map((r) => {
            const svc = r.service ? data.services.find((s) => s.name === r.service) : null;
            return (
              <div className="tr" key={r.full_name}>
                <div className="cell-title">
                  <a className="row-title" href={r.url} target="_blank" rel="noreferrer">
                    {r.name} <ExternalLink size={11} />
                  </a>
                  <span className="muted small">{r.description || "no description"}</span>
                </div>
                <div className="muted small">{r.pushed_at ? `pushed ${fmtAgo(r.pushed_at)}` : ""}</div>
                <div>
                  {svc ? (
                    <Pill tone={svc.learned ? "green" : "grey"}>part of {svc.name}</Pill>
                  ) : (
                    <span className="faint small">not in the knowledge base</span>
                  )}
                </div>
                <div className="cell-actions">
                  {svc ? (
                    <button className={cx("btn btn-ghost", { hint: locked })} onClick={() => (svc.plans[0] ? navigate(`/plans/${svc.plans[0]}`) : plan(svc))} disabled={busy === svc.name}>
                      {svc.plans[0] ? "Open pipeline" : "Migrate"}
                    </button>
                  ) : (
                    <span className="faint small" title="Document it in the knowledge base first">
                      —
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
