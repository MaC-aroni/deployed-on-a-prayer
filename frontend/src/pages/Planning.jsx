import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Bot, ExternalLink, OctagonX, RotateCw, Sparkles } from "lucide-react";
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
  if (step === "detect") return mine.length ? "succeeded" : active ? "running" : "skipped";
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
  if (step === "detect") return text || "looking for a migration.yaml";
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
    const d = stateOf("detect", events, active);
    const p = stateOf("plan", events, active);
    const detected = Boolean(run?.report?.detected) || /found reviewed/.test(subOf("detect", events));
    const cols = [
      { id: "detect", name: "Detect", status: d, steps: [{ id: "detect", name: "migration.yaml?", sub: subOf("detect", events), status: d, agent: true, aside: <Sparkles size={14} className="nemotron" /> }] },
    ];
    if (!detected) {
      cols.push(
        { id: "knowledge", name: "Knowledge", status: k, steps: [{ id: "knowledge", name: "Knowledge graph", sub: subOf("knowledge", events), status: k, agent: true, aside: <Sparkles size={14} className="nemotron" /> }] },
        { id: "planner", name: "Nemotron planner", status: attemptSteps.at(-1)?.status ?? "pending", steps: attemptSteps },
      );
    }
    cols.push({ id: "plan", name: "Pipeline", status: p, steps: [{ id: "plan", name: detected ? "reviewed migration.yaml" : "migration.yaml", sub: subOf("plan", events), status: p }] });
    return cols;
  }, [attempts, events, active, run?.report?.detected]);

  const edges = useMemo(() => {
    const ids = columns.flatMap((c) => c.steps.map((s) => s.id));
    return ids.slice(1).map((to, i) => ({ from: ids[i], to }));
  }, [columns]);

  const selectedLines = events.filter((e) => e.step === selected);
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [selectedLines.length]);

  async function cancel() {
    setBusy(true);
    try {
      await api.cancel(run.id);
      setRun(await api.run(run.id));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

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
  const pipeline = report.detected ? `/migrations/${encodeURIComponent(report.detected)}` : `/plans/${run.id}`;
  const pipelineHref = report.build_run ? `${pipeline}?run=${report.build_run}` : pipeline;

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
            {report.iterations > 0 && <span>{report.iterations} attempt{report.iterations === 1 ? "" : "s"}</span>}
            {report.detected && <span>reviewed migration.yaml found</span>}
            {report.build_run && <span className="mono">Build {report.build_run} started</span>}
            {run.reason && (
              <span className="run-reason" title={run.reason}>
                {run.reason}
              </span>
            )}
          </div>
        </div>
        <div className="run-actions">
          <Link to={`/agents/${run.id}`} className="btn" title="Every agent this run launched">
            <Bot size={14} /> Agents
          </Link>
          {report.pr_url && (
            <a className="btn" href={report.pr_url} target="_blank" rel="noreferrer">
              Pull request <ExternalLink size={13} />
            </a>
          )}
          {run.active && (
            <button className={cx("btn btn-danger", { hint: locked })} onClick={cancel} disabled={busy} title="Stop the agent before its next step. Nothing to undo: a plan changes nothing until it opens its PR.">
              <OctagonX size={14} /> Cancel
            </button>
          )}
          {(run.status === "failed" || run.status === "cancelled") && (
            <button className={cx("btn", { hint: locked })} onClick={tryAgain} disabled={busy}>
              <RotateCw size={14} /> Try again
            </button>
          )}
          {run.status === "succeeded" && (
            <Link to={pipelineHref} className="btn btn-primary">
              {report.build_run ? "Open pipeline · Build running" : "Open pipeline"} <ArrowRight size={14} />
            </Link>
          )}
        </div>
      </div>

      <div className="dag-frame">
        <Dag columns={columns} edges={edges} selectedId={selected} onSelect={(id) => setSelected(id === selected ? null : id)} onAgent={() => navigate(`/agents/${runId}`)} />
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
