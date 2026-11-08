import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpen, ExternalLink, Sparkles } from "lucide-react";
import Dag from "../components/Dag.jsx";
import FixCard from "../components/FixCard.jsx";
import { EmptyState, useAuth } from "../components/Shell.jsx";
import StatusIcon, { Pill } from "../components/StatusIcon.jsx";
import { api, fmtTime, follow, parseAgent } from "../mac/api.js";
import { DEMO_AGENT_SETS } from "../data/mock.js";
import { Link, navigate } from "../router.jsx";
import { MODE_LABEL, runMeta } from "../status.js";
import { cx } from "../lib.js";

// The agent view: every agent a run launched, as a hierarchy. A Director directs workers (one
// reads and compresses pages, one checks references, …) whose results feed a Compiler that
// writes the page or the plan and raises the Jira ticket. Everything comes from the run's
// `agent` events (docs/planning-api.md); /agents/demo replays a mock Learn for the pitch.

const COLLAPSE_AT = 6;

export function buildAgents(events, run) {
  const byId = new Map();
  for (const ev of events) {
    const a = parseAgent(ev);
    if (!a) continue;
    const cur = byId.get(a.agent) ?? { id: a.agent, role: null, parent: null, model: null, lines: [], status: "pending", first: a.ts, step: a.step };
    cur.role ??= a.role;
    cur.parent ??= a.parent;
    cur.model ??= a.model;
    cur.lines.push(a);
    if (a.status) cur.status = a.status;
    else if (cur.status === "pending" && a.phase !== "observation") cur.status = "running";
    cur.last = a.ts;
    byId.set(a.agent, cur);
  }
  const agents = [...byId.values()];
  if (run && !run.active) {
    for (const a of agents) if (a.status === "running" || a.status === "pending") a.status = run.status === "succeeded" ? "succeeded" : a.status === "running" ? "failed" : "skipped";
  }
  return agents;
}

function label(agent) {
  if (agent.role) return agent.role;
  const [kind, rest] = agent.id.split(":");
  return rest ? `${kind} · ${rest}` : kind;
}

function sub(agent) {
  const last = agent.lines.at(-1);
  return last ? last.text : "";
}

function aggregate(statuses) {
  if (statuses.includes("failed")) return "failed";
  if (statuses.includes("running")) return "running";
  if (statuses.length && statuses.every((s) => s === "succeeded")) return "succeeded";
  if (statuses.length && statuses.every((s) => s === "skipped")) return "skipped";
  return "pending";
}

function titleOf(run) {
  if (!run) return "";
  if (run.mode === "plan") return (run.migration ?? "").replace(/^plan\//, "").replaceAll("-", " ").replace(/^approvals$/, "raise approvals in Jira");
  if (run.mode === "diagnose") return `Diagnose ${run.failed_step ?? run.report?.step ?? "the failure"}`;
  if ((run.migration ?? "").startsWith("knowledge/")) return `Learn ${run.migration.slice("knowledge/".length)}`;
  if ((run.migration ?? "").startsWith("repo/")) return `Licence check · ${run.migration.slice("repo/".length)}`;
  return "Learn the knowledge base";
}

function backLink(run) {
  if (!run) return { to: "/migrate", label: "Migration" };
  if (run.mode === "plan") return { to: `/migrate/${run.id}`, label: "planning run" };
  if (run.id === "demo") return { to: "/demo", label: "pitch demo" };
  if (run.mode === "diagnose") return { to: `/migrations/${encodeURIComponent(run.migration)}?run=${run.based_on ?? ""}`, label: "pipeline" };
  return { to: "/migrate", label: "Migration" };
}

// Which mock hierarchy to replay: /agents/demo?for=<step id of the pitch pipeline>.
function demoSet() {
  const key = new URLSearchParams(window.location.search).get("for");
  return DEMO_AGENT_SETS[key] ?? DEMO_AGENT_SETS.learn_kb;
}

function useDemoReplay(events) {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0);
  }, [events]);
  useEffect(() => {
    if (n >= events.length) return;
    const id = setTimeout(() => setN((v) => v + 1), n === 0 ? 300 : 650);
    return () => clearTimeout(id);
  }, [n, events]);
  return { events: events.slice(0, n), done: n >= events.length, restart: () => setN(0) };
}

export default function Agents({ runId }) {
  const { locked } = useAuth();
  const demo = runId === "demo";
  const set = useMemo(() => (demo ? demoSet() : null), [demo]); // eslint-disable-line react-hooks/exhaustive-deps
  const [run, setRun] = useState(demo ? set.run : null);
  const [events, setEvents] = useState([]);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const replay = useDemoReplay(set?.events ?? []);

  useEffect(() => {
    if (demo) return;
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
            if (ev.kind === "run" || ev.kind === "step") api.run(runId).then((nr) => alive && setRun(nr)).catch(() => {});
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
  }, [runId, demo]);

  const shownEvents = demo ? replay.events : events;
  const shownRun = demo ? { ...set.run, active: !replay.done, status: replay.done ? "succeeded" : "running" } : run;
  const agents = useMemo(() => buildAgents(shownEvents, shownRun), [shownEvents, shownRun]);

  const { columns, edges, groups } = useMemo(() => {
    const director = agents.find((a) => !a.parent) ?? null;
    const compiler = agents.find((a) => a.id === "compiler") ?? null;
    const workers = agents.filter((a) => a !== director && a !== compiler);
    const groups = {};
    let workerNodes = workers;
    const readers = workers.filter((a) => a.id.startsWith("reader:"));
    if (readers.length > COLLAPSE_AT) {
      const done = readers.filter((a) => a.status === "succeeded").length;
      groups.readers = readers;
      workerNodes = [
        { id: "readers", role: "Readers", status: aggregate(readers.map((a) => a.status)), lines: [], group: true, sub: `${done} of ${readers.length} pages compressed` },
        ...workers.filter((a) => !a.id.startsWith("reader:")),
      ];
    }
    const node = (a) => ({ id: a.id, name: label(a), sub: a.sub ?? sub(a), status: a.status, agent: true, aside: <Sparkles size={14} className="nemotron" /> });
    const columns = [];
    if (director) columns.push({ id: "director", name: "Director", status: director.status, steps: [node(director)] });
    if (workerNodes.length) columns.push({ id: "workers", name: "Workers", status: aggregate(workerNodes.map((a) => a.status)), steps: workerNodes.map(node) });
    if (compiler) columns.push({ id: "compile", name: "Compile", status: compiler.status, steps: [node(compiler)] });
    const edges = [];
    if (director) for (const w of workerNodes) edges.push({ from: director.id, to: w.id });
    if (compiler) {
      if (workerNodes.length) for (const w of workerNodes) edges.push({ from: w.id, to: compiler.id });
      else if (director) edges.push({ from: director.id, to: compiler.id });
    }
    return { columns, edges, groups };
  }, [agents]);

  const picked = selected === "readers" ? { id: "readers", role: "Readers", lines: (groups.readers ?? []).flatMap((a) => a.lines).sort((x, y) => x.seq - y.seq), model: groups.readers?.[0]?.model } : agents.find((a) => a.id === selected);

  async function approve() {
    setBusy(true);
    try {
      const r = await api.approveFix(run.id);
      setRun(r);
      setToast({ tone: "green", text: `Fix approved: ${r.report.pr_url}` });
    } catch (e) {
      setToast({ tone: e.status === 409 ? "amber" : "red", text: e.detail ?? String(e) });
    } finally {
      setBusy(false);
    }
  }

  if (error) return <EmptyState title="Couldn't load this run" body={error.detail ?? String(error)} />;
  if (!shownRun) return <EmptyState title="Loading…" />;

  const meta = runMeta(shownRun.status, shownRun.mode);
  const back = backLink(shownRun);
  const rep = shownRun.report ?? {};
  const model = agents.find((a) => a.model)?.model;

  return (
    <>
      {toast && (
        <div className={cx("toast", `tone-${toast.tone}`)} role="status" onClick={() => setToast(null)}>
          {toast.text}
        </div>
      )}
      {demo && (
        <div className="demo-banner">
          <Sparkles size={14} className="nemotron" />
          Pitch rehearsal: a mock agent run. Live agent runs open here from any working-agent icon.
          <button className="link-btn" onClick={replay.restart} style={{ marginLeft: "auto" }}>
            Replay
          </button>
        </div>
      )}

      <div className="run-head">
        <div className="run-head-main">
          <Pill tone={meta.tone} className="pill-lg">
            <StatusIcon status={meta.icon} size={16} agent />
            {MODE_LABEL[shownRun.mode] ?? shownRun.mode} · {meta.label}
          </Pill>
          <h1 style={{ textTransform: shownRun.mode === "plan" ? "capitalize" : "none" }}>{titleOf(shownRun)}</h1>
          <div className="run-meta">
            <span className="mono">run {shownRun.id}</span>
            <span>{fmtTime(shownRun.created)}</span>
            {model && (
              <span className="model">
                <Sparkles size={12} /> {model}
              </span>
            )}
            <span>
              {agents.length} agent{agents.length === 1 ? "" : "s"}
            </span>
            {shownRun.active && (
              <span className="live">
                <span className="live-dot" /> live
              </span>
            )}
            {shownRun.reason && (
              <span className="run-reason" title={shownRun.reason}>
                {shownRun.reason}
              </span>
            )}
          </div>
        </div>
        <div className="run-actions">
          <div className="actions-row">
            <Link to={back.to} className="btn">
              <ArrowLeft size={14} /> Back to {back.label}
            </Link>
            {rep.page && (
              <Link to={`/knowledge/${rep.page}`} className="btn">
                <BookOpen size={14} /> Knowledge page
              </Link>
            )}
            {rep.ticket && (
              <a className="btn" href={rep.ticket_url ?? "#"} target="_blank" rel="noreferrer">
                {rep.ticket} <ExternalLink size={12} />
              </a>
            )}
            {shownRun.mode === "plan" && shownRun.status === "succeeded" && (
              <Link to={rep.detected ? `/migrations/${encodeURIComponent(rep.detected)}` : `/plans/${shownRun.id}`} className="btn btn-primary">
                Open pipeline <ArrowRight size={14} />
              </Link>
            )}
          </div>
        </div>
      </div>

      <div className="dag-frame">
        <Dag columns={columns} edges={edges} selectedId={selected} onSelect={(id) => setSelected(id === selected ? null : id)} onAgent={(id) => setSelected(id)} emptyHint={shownRun.active ? "The Director hasn't reported yet…" : "This run recorded no agent trace."} />
      </div>

      {shownRun.mode === "diagnose" && !demo && <FixCard run={shownRun} onApprove={approve} busy={busy} locked={locked} />}

      {picked && (
        <section className="inspector">
          <header className="inspector-head">
            <StatusIcon status={picked.status ?? aggregate(picked.lines.map(() => "succeeded"))} size={28} agent />
            <div className="inspector-title">
              <h2>{label(picked)}</h2>
              <span className="muted small mono">{picked.id}</span>
            </div>
            <div className="inspector-meta">
              {picked.model && (
                <span className="meta-chip model">
                  <Sparkles size={12} /> {picked.model}
                </span>
              )}
              {picked.parent && <span className="meta-chip">directed by {picked.parent}</span>}
            </div>
          </header>
          <div className="inspector-body agent-trace">
            {picked.lines.length === 0 ? (
              <p className="muted small">nothing yet</p>
            ) : (
              <ol className="trace">
                {picked.lines.map((line) => (
                  <li key={line.seq} className={cx("trace-line", `k-${line.phase}`)}>
                    <span className="trace-kind">{line.phase}</span>
                    <p>
                      {picked.id === "readers" && <span className="mono muted">{line.agent.split(":")[1]} · </span>}
                      {line.text}
                    </p>
                    <span className="mono small muted trace-time">{fmtTime(line.ts)}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>
      )}
    </>
  );
}

export function openAgents(runId) {
  navigate(`/agents/${runId}`);
}
