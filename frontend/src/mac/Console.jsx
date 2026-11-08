import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, follow, getToken, setToken } from "./api.js";
import "./console.css";

const ICON = {
  succeeded: "✓", failed: "✕", running: "", waiting: "▶", blocked: "🔒", pending: "○",
  skipped: "»", rolled_back: "↺", rollback_failed: "!", none: "–",
};
const AI_MODES = [["explain", "Explain"], ["report", "Report"], ["autofix", "Auto-fix"]];

function StatusBadge({ status }) {
  return <span className={`badge badge-${status}`}>{status?.replace("_", " ")}</span>;
}

function JobCard({ step, state, selected, onSelect, onPlay }) {
  const s = state || "none";
  return (
    <div className={`job job-${s} ${selected ? "job-selected" : ""}`} onClick={() => onSelect(step.id)}
         title={`${step.type} · ${step.repo}${step.path ? ` · ${step.path}` : step.entrypoint ? ` · ${step.entrypoint}` : ""}`}>
      <span className={`job-icon icon-${s}`}>{ICON[s]}</span>
      <span className="job-name">{step.id}</span>
      {step.codegen === "llm" && <span className="tag tag-ai" title="codegen: llm — the LLM writes this step's code, as a reviewed PR">AI</span>}
      {step.requires_approval.length > 0 && <span className="tag" title={step.requires_approval.join(", ")}>🔒{step.requires_approval.length}</span>}
      {s === "waiting" && (
        <button className="play" onClick={(e) => { e.stopPropagation(); onPlay(step.id); }} title="Run this manual step">▶</button>
      )}
    </div>
  );
}

function Pipeline({ detail, run, selected, onSelect, onPlay }) {
  return (
    <div className="pipeline">
      {detail.stages.map((stage, i) => (
        <div className="stage" key={stage.name}>
          <div className="stage-name">{stage.name}</div>
          {stage.steps.map((step) => (
            <JobCard key={step.id} step={step} state={run?.steps?.[step.id]} selected={selected === step.id}
                     onSelect={onSelect} onPlay={onPlay} />
          ))}
          {i < detail.stages.length - 1 && <div className="connector" />}
        </div>
      ))}
    </div>
  );
}

function LogPanel({ run, events, step, onClose }) {
  const lines = events.filter((e) => (step ? e.step === step : true) && e.kind !== "step");
  const box = useRef(null);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [lines.length]);
  return (
    <div className="logs">
      <div className="logs-head">
        <strong>{step || "All events"}</strong> <span className="muted">run {run.id}</span>
        {step && <button className="link" onClick={onClose}>show all</button>}
      </div>
      <pre ref={box}>
        {lines.length === 0 ? "No output yet." : lines.map((e) => (
          <div key={e.seq} className={`line line-${e.kind}`}>{e.kind === "log" ? "" : "==> "}{!step && e.step ? `[${e.step}] ` : ""}{e.message}</div>
        ))}
      </pre>
    </div>
  );
}

function Approvals({ detail, build }) {
  const report = build?.report?.approvals || {};
  return (
    <div className="card">
      <h3>Approvals</h3>
      {detail.design_page && (
        <p className="muted">Design page: <a href={detail.design_page.url} target="_blank" rel="noreferrer">Confluence</a>
          {!detail.design_page.current && " (out of date: run Build)"}</p>
      )}
      <ul className="approvals">
        {detail.approvals.map((a) => {
          const r = report[a.id] || {};
          return (
            <li key={a.id}>
              <StatusBadge status={r.status || "pending"} /> <strong>{a.id}</strong> <span className="muted">from {a.approver}</span>
              {a.ticket && <> · <a href={a.ticket.url} target="_blank" rel="noreferrer">{a.ticket.key}</a></>}
              <div className="muted small">{a.summary}{r.detail && r.detail !== a.ticket?.key ? ` · ${r.detail}` : ""}</div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function Console() {
  const [migrations, setMigrations] = useState([]);
  const [name, setName] = useState(null);
  const [detail, setDetail] = useState(null);
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState(null);
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [selected, setSelected] = useState(null);
  const [ai, setAi] = useState("explain");
  const [error, setError] = useState(null);
  const [needsToken, setNeedsToken] = useState(false);

  const fail = useCallback((e) => {
    if (e.status === 401 || e.status === 503) setNeedsToken(true);
    setError(e.message);
  }, []);

  const refresh = useCallback(async (migration = name, id = runId) => {
    if (!migration) return;
    try {
      const [d, r] = await Promise.all([api.migration(migration), api.runs(migration)]);
      setDetail(d);
      setRuns(r);
      const pick = id || d.active_run?.id || r[0]?.id;
      if (pick) {
        setRunId(pick);
        setRun(await api.run(pick));
      }
    } catch (e) { fail(e); }
  }, [name, runId, fail]);

  useEffect(() => {
    api.migrations().then((list) => { setMigrations(list); if (list[0]) setName(list[0].name); }).catch(fail);
  }, [fail]);
  useEffect(() => { if (name) { setRunId(null); refresh(name, null); } }, [name]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (detail) setAi(detail.diagnostics_default); }, [detail?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load the selected run's events, and stream new ones while it's active.
  useEffect(() => {
    if (!runId) return undefined;
    let stop = () => {};
    let cancelled = false;
    api.events(runId).then((list) => {
      if (cancelled) return;
      setEvents(list);
      const last = list.at(-1)?.seq || 0;
      stop = follow(runId, last, (ev) => {
        setEvents((prev) => (prev.some((p) => p.seq === ev.seq) ? prev : [...prev, ev]));
        if (ev.kind !== "log") api.run(runId).then(setRun).catch(() => {});
      }, () => refresh(name, runId));
    }).catch(fail);
    return () => { cancelled = true; stop(); };
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn) => {
    setError(null);
    try {
      const started = await fn();
      if (started?.id) { setRunId(started.id); setSelected(null); }
      await refresh(name, started?.id || runId);
    } catch (e) { fail(e); }
  };

  const latest = detail?.latest || {};
  const busy = Boolean(detail?.active_run);
  const lastBuild = useMemo(() => runs.find((r) => r.mode === "build"), [runs]);
  const [buildRun, setBuildRun] = useState(null);
  useEffect(() => { if (lastBuild) api.run(lastBuild.id).then(setBuildRun).catch(() => {}); }, [lastBuild?.id, lastBuild?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="mac">
      <header className="topbar">
        <span className="logo">MaC</span><span className="muted">Migration as Code</span>
        <span className="spacer" />
        <input className="token" type="password" placeholder="API token (Fly only)" defaultValue={getToken()}
               onBlur={(e) => { setToken(e.target.value.trim()); if (needsToken) window.location.reload(); }} />
      </header>
      <div className="layout">
        <aside className="sidebar">
          <div className="sidebar-title">Migrations</div>
          {migrations.map((m) => (
            <button key={m.name} className={`migration ${m.name === name ? "active" : ""}`} onClick={() => setName(m.name)}>
              <div>{m.service || m.name}</div><div className="muted small">{m.name}</div>
              {!m.valid && <div className="error small">invalid</div>}
            </button>
          ))}
        </aside>
        <main className="main">
          {error && <div className="banner" onClick={() => setError(null)}>{error}</div>}
          {needsToken && <div className="banner">This server needs the MaC API token: paste it top right.</div>}
          {detail && (
            <>
              <div className="title-row">
                <div>
                  <h1>{detail.service}</h1>
                  <div className="muted">{detail.name} · {detail.target.provider.toUpperCase()} {detail.target.region} · owner {detail.owner_team}</div>
                </div>
                <div className="actions">
                  <div className="segmented" title="AI help if a step fails">
                    {AI_MODES.map(([value, label]) => (
                      <button key={value} className={ai === value ? "on" : ""} onClick={() => setAi(value)}>{label}</button>
                    ))}
                  </div>
                  <button className="btn" disabled={busy} onClick={() => act(() => api.start(name, "build"))}>Build</button>
                  <button className="btn" disabled={busy || latest.build?.status !== "succeeded"}
                          title={latest.build?.status !== "succeeded" ? "Needs a passing Build" : ""}
                          onClick={() => act(() => api.start(name, "rehearse", ai))}>Rehearse</button>
                  <button className="btn btn-primary" disabled={busy || latest.rehearse?.status !== "succeeded"}
                          title={latest.rehearse?.status !== "succeeded" ? "Needs a passing Rehearse" : ""}
                          onClick={() => act(() => api.start(name, "deploy", ai === "autofix" ? "report" : ai))}>Deploy</button>
                </div>
              </div>

              {run && (
                <div className="run-head">
                  <StatusBadge status={run.status} />
                  <strong>{run.mode} #{run.id}</strong>
                  <span className="muted">{new Date(run.created * 1000).toLocaleString()}</span>
                  {run.reason && <span className="reason">{run.reason}</span>}
                  <span className="spacer" />
                  {run.status === "waiting" && <button className="btn" onClick={() => act(() => api.resume(run.id))}>Check approvals</button>}
                  {(run.status === "waiting" || (run.mode === "deploy" && run.status === "succeeded")) && (
                    <button className="btn btn-danger" onClick={() => act(() => api.undo(run.id))}>Undo</button>
                  )}
                </div>
              )}

              <Pipeline detail={detail} run={run} selected={selected} onSelect={setSelected}
                        onPlay={(step) => act(() => api.play(run.id, step))} />

              <div className="grid">
                {run && <LogPanel run={run} events={events} step={selected} onClose={() => setSelected(null)} />}
                <div className="side-cards">
                  <Approvals detail={detail} build={buildRun} />
                  <div className="card">
                    <h3>Runs</h3>
                    <ul className="runs">
                      {runs.map((r) => (
                        <li key={r.id} className={r.id === runId ? "active" : ""} onClick={() => { setSelected(null); setRunId(r.id); api.run(r.id).then(setRun); }}>
                          <StatusBadge status={r.status} /> {r.mode} <span className="muted">#{r.id}</span>
                        </li>
                      ))}
                      {runs.length === 0 && <li className="muted">No runs yet. Start with Build.</li>}
                    </ul>
                  </div>
                </div>
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
