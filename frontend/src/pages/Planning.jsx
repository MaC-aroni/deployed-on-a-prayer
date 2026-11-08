import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, ExternalLink, RotateCw, Sparkles } from "lucide-react";
import Dag from "../components/Dag.jsx";
import { EmptyState, useAuth } from "../components/Shell.jsx";
import StatusIcon, { Pill } from "../components/StatusIcon.jsx";
import { api, fmtTime, follow } from "../mac/api.js";
import { Link, navigate } from "../router.jsx";
import { runMeta } from "../status.js";
import { cx } from "../lib.js";

// The agent phase of a migration, drawn like a pipeline: knowledge → planner attempts → plan.
// Everything here comes from one run's events (docs/planning-api.md).

function stateOf(step, evs, active) {
  const mine = evs.filter((e) => e.step === step && e.kind === "step");
  const last = mine.at(-1)?.message ?? "";
  if (step === "knowledge") {
    if (/failed/.test(last)) return "failed";
    if (/graph loaded|facts/.test(last)) return "succeeded";
    return mine.length ? "running" : active ? "pending" : "skipped";
  }
  if (step.startsWith("attempt-")) {
    if (/: valid$/.test(last)) return "succeeded";
    if (/problems/.test(last)) return "failed";
    if (/running/.test(last)) return active ? "running" : "failed";
    return "pending";
  }
  if (/written|opened/.test(last)) return "succeeded";
  if (/not valid|failed/.test(last)) return "failed";
  return active ? "pending" : "skipped";
}

function subOf(step, evs) {
  const mine = evs.filter((e) => e.step === step);
  const last = mine.filter((e) => e.kind === "step").at(-1)?.message ?? "";
  const text = last.replace(/^[a-z0-9-]+: /, "");
  if (step.startsWith("attempt-")) {
    const problems = mine.filter((e) => e.kind === "log").length;
    if (/valid$/.test(last)) return "valid: schema, validator, citations, documented repos";
    if (problems) return `${problems} problem${problems === 1 ? "" : "s"} sent back to the model`;
    return text || "waiting";
  }
  return text || (step === "knowledge" ? "Confluence pages → graph" : "migration.yaml");
}

export default function Planning({ runId }) {
  const { locked } = useAuth();
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [yaml, setYaml] = useState(null); // the generated migration.yaml, from GET /plans/{id}
  const logRef = useRef(null);

  useEffect(() => {
    if (run?.status !== "succeeded") return;
    api.planDetail(runId).then((d) => setYaml(d.yaml)).catch(() => setYaml(null));
  }, [run?.status, runId]);

  useEffect(() => {
    let alive = true;
    let stop = () => {};
    (async () => {
      try {
        const [r, evs] = await Promise.all([api.run(runId), api.events(runId)]);
        if (!alive) return;
        setRun(r);
        setEvents(evs);
        if (!r.active) return;
        stop = follow(
          runId,
          evs.at(-1)?.seq ?? 0,
          (ev) => {
            if (!alive) return;
            setEvents((prev) => (prev.some((p) => p.seq === ev.seq) ? prev : [...prev, ev]));
            if (ev.kind !== "log") api.run(runId).then((nr) => alive && setRun(nr)).catch(() => {});
          },
          () => alive && api.run(runId).then((nr) => alive && setRun(nr)).catch(() => {}),
        );
      } catch (e) {
        if (alive) setError(e);
      }
    })();
    return () => {
      alive = false;
      stop();
    };
  }, [runId]);

  const attempts = useMemo(() => {
    const ids = new Set(events.filter((e) => e.step?.startsWith("attempt-")).map((e) => e.step));
    return [...ids].sort((a, b) => Number(a.split("-")[1]) - Number(b.split("-")[1]));
  }, [events]);

  const active = Boolean(run?.active);
  const columns = useMemo(() => {
    const attemptSteps = (attempts.length ? attempts : ["attempt-1"]).map((id) => ({
      id,
      name: `Attempt ${id.split("-")[1]}`,
      sub: subOf(id, events),
      status: stateOf(id, events, active),
      agent: true,
      aside: <Sparkles size={14} className="nemotron" />,
    }));
    const k = stateOf("knowledge", events, active);
    const p = stateOf("plan", events, active);
    return [
      { id: "knowledge", name: "Knowledge", status: k, steps: [{ id: "knowledge", name: "Knowledge graph", sub: subOf("knowledge", events), status: k, agent: true, aside: <Sparkles size={14} className="nemotron" /> }] },
      { id: "planner", name: "Nemotron planner", status: attemptSteps.at(-1)?.status ?? "pending", steps: attemptSteps },
      { id: "plan", name: "Plan", status: p, steps: [{ id: "plan", name: "migration.yaml", sub: subOf("plan", events), status: p }] },
    ];
  }, [attempts, events, active]);

  const edges = useMemo(() => {
    const chain = ["knowledge", ...(attempts.length ? attempts : ["attempt-1"]), "plan"];
    return chain.slice(1).map((to, i) => ({ from: chain[i], to }));
  }, [attempts]);

  const selectedLines = events.filter((e) => e.step === selected);
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [selectedLines.length]);

  async function tryAgain() {
    setBusy(true);
    try {
      const r = await api.plan({ goal: goal });
      navigate(`/migrate/${r.id}`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <EmptyState title="Couldn't load this planning run" body={error.detail ?? String(error)} />;
  if (!run) return <EmptyState title="Loading…" />;

  const meta = runMeta(run.status, run.mode);
  const goal = (run.migration ?? "").replace(/^plan\//, "").replaceAll("-", " ");
  const report = run.report ?? {};

  return (
    <>
      <div className="run-head">
        <div className="run-head-main">
          <Pill tone={meta.tone} className="pill-lg">
            <StatusIcon status={meta.icon} size={16} agent />
            {meta.label}
          </Pill>
          <h1 style={{ textTransform: "capitalize" }}>{goal}</h1>
          <div className="run-meta">
            <span className="mono">run {run.id}</span>
            <span>{fmtTime(run.created)}</span>
            {report.iterations && <span>{report.iterations} attempt{report.iterations === 1 ? "" : "s"}</span>}
            {run.reason && (
              <span className="run-reason" title={run.reason}>
                {run.reason}
              </span>
            )}
          </div>
        </div>
        <div className="run-actions">
          {report.pr_url && (
            <a className="btn" href={report.pr_url} target="_blank" rel="noreferrer">
              Pull request <ExternalLink size={13} />
            </a>
          )}
          {run.status === "failed" && (
            <button className={cx("btn", { hint: locked })} onClick={tryAgain} disabled={busy}>
              <RotateCw size={14} /> Try again
            </button>
          )}
          {run.status === "succeeded" && (
            <Link to={`/plans/${run.id}`} className="btn btn-primary">
              Open pipeline <ArrowRight size={14} />
            </Link>
          )}
        </div>
      </div>

      <div className="dag-frame">
        <Dag columns={columns} edges={edges} selectedId={selected} onSelect={(id) => setSelected(id === selected ? null : id)} />
      </div>

      {selected && (
        <section className="inspector">
          <header className="inspector-head">
            <StatusIcon status={stateOf(selected, events, active)} size={28} agent />
            <div className="inspector-title">
              <h2 className="mono">{selected}</h2>
              <span className="muted small">{subOf(selected, events)}</span>
            </div>
            <div className="inspector-meta">
              {selected.startsWith("attempt-") && (
                <span className="meta-chip model">
                  <Sparkles size={12} /> validator feedback → model
                </span>
              )}
            </div>
          </header>
          <div className="inspector-split">
            <nav className="tabs tabs-vertical">
              <button className="tab active">{selected === "plan" && yaml ? "migration.yaml" : "Events"}</button>
            </nav>
            <div className="inspector-body">
              {selected === "plan" && yaml ? (
                <pre className="log yaml">{yaml}</pre>
              ) : (
                <pre className="log" ref={logRef}>
                  {selectedLines.length === 0 ? "nothing yet" : selectedLines.map((e) => `${fmtTime(e.ts)}  ${e.kind === "log" ? "" : `[${e.kind}] `}${e.message}`).join("\n")}
                </pre>
              )}
            </div>
          </div>
        </section>
      )}
    </>
  );
}
