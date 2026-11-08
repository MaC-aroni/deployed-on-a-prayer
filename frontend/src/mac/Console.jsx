import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, follow } from "./api.js";
import ApprovalsTab from "./components/ApprovalsTab.jsx";
import Badge from "./components/Badge.jsx";
import BuildReport from "./components/BuildReport.jsx";
import DiagnosisCard from "./components/DiagnosisCard.jsx";
import { JobDetails, JobLog } from "./components/JobPanel.jsx";
import JobsTable from "./components/JobsTable.jsx";
import Modal from "./components/Modal.jsx";
import PipelineGraph from "./components/PipelineGraph.jsx";
import RunsTab from "./components/RunsTab.jsx";
import Sidebar from "./components/Sidebar.jsx";
import StatusIcon from "./components/StatusIcon.jsx";
import TopBar from "./components/TopBar.jsx";
import { MODE_LABEL, absTime, fmtDuration, maskAccount, requestedBy, runDuration, shortSha, stepTimings, timeAgo } from "./util.js";
import "./console.css";

const AI_MODES = [["explain", "Explain"], ["report", "Report"], ["autofix", "Auto-fix"]];
const AI_HELP = {
  explain: "reads the logs and says what went wrong and the likely cause",
  report: "also reads the failing repo's code and writes a report for your coding agent",
  autofix: "also fixes the code on a branch and re-runs Build and Rehearse, up to 3 times, then opens a PR",
};
const SIGN_IN_PROBLEMS = {
  "no-access": "That GitHub account can't push to MaC-aroni/deployed-on-a-prayer, so it can't run pipelines.",
  expired: "The sign-in took too long or was started in another tab. Try again.",
  failed: "GitHub didn't complete the sign-in. Try again.",
};
const TABS = ["Pipeline", "Jobs", "Build report", "Approvals", "Runs"];

function readUrl() {
  const q = new URLSearchParams(window.location.search);
  return { m: q.get("m"), run: q.get("run"), step: q.get("step"), tab: q.get("tab"), signin: q.get("signin") };
}

function writeUrl(parts) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(parts)) if (v) q.set(k, v);
  const url = `${window.location.pathname}${q.toString() ? `?${q}` : ""}`;
  if (url !== window.location.pathname + window.location.search) window.history.replaceState(null, "", url);
}

export default function Console() {
  const initial = useRef(readUrl());
  const [migrations, setMigrations] = useState([]);
  const [name, setName] = useState(initial.current.m);
  const [detail, setDetail] = useState(null);
  const [runs, setRuns] = useState([]);
  const [runDetails, setRunDetails] = useState({});
  const [requesters, setRequesters] = useState({});
  const [runId, setRunId] = useState(initial.current.run);
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [selected, setSelected] = useState(initial.current.step);
  const [tab, setTab] = useState(TABS.includes(initial.current.tab) ? initial.current.tab : "Pipeline");
  const [ai, setAi] = useState("explain");
  const [error, setError] = useState(SIGN_IN_PROBLEMS[initial.current.signin] || (initial.current.signin ? "Sign-in failed." : null));
  const [me, setMe] = useState(null);
  const [live, setLive] = useState("off");
  const [modal, setModal] = useState(null);
  const [shake, setShake] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [buildEvents, setBuildEvents] = useState([]);
  const [unreachable, setUnreachable] = useState(false);

  const fail = useCallback((e) => {
    if (e instanceof TypeError) { setUnreachable(true); return; } // fetch failed: the API is down
    setUnreachable(false);
    setError(e.message);
  }, []);

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe({ login: null, required: false, available: false }));
  }, []);

  const refresh = useCallback(async (migration = name, id = runId) => {
    if (!migration) return;
    try {
      const [d, r] = await Promise.all([api.migration(migration), api.runs(migration)]);
      setUnreachable(false);
      setDetail(d);
      setRuns(r);
      const pick = (id && r.some((x) => x.id === id) ? id : null) || d.active_run?.id || r[0]?.id || null;
      setRunId(pick);
      if (pick) {
        const full = await api.run(pick);
        setRun(full);
        setRunDetails((prev) => ({ ...prev, [pick]: full }));
      } else {
        setRun(null);
      }
    } catch (e) { fail(e); }
  }, [name, runId, fail]);

  useEffect(() => {
    api.migrations().then((list) => {
      setMigrations(list);
      setUnreachable(false);
      if (!list.some((m) => m.name === name)) setName(list[0]?.name || null);
    }).catch(fail);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (name) refresh(name, initial.current.run); initial.current.run = null; }, [name]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (detail) setAi(detail.diagnostics_default); }, [detail?.name]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { writeUrl({ m: name, run: runId, step: selected, tab: tab === "Pipeline" ? null : tab }); }, [name, runId, selected, tab]);

  // Load the shown run's events, then stream new ones while it's active.
  useEffect(() => {
    if (!runId) { setEvents([]); setLive("off"); return undefined; }
    let stop = () => {};
    let cancelled = false;
    api.events(runId).then((list) => {
      if (cancelled) return;
      setEvents(list);
      const who = requestedBy(list);
      if (who) setRequesters((prev) => ({ ...prev, [runId]: who }));
      const last = list.at(-1)?.seq || 0;
      stop = follow(runId, last, (ev) => {
        setEvents((prev) => (prev.some((p) => p.seq === ev.seq) ? prev : [...prev, ev]));
        if (ev.kind !== "log") api.run(runId).then((full) => { setRun(full); setRunDetails((prev) => ({ ...prev, [runId]: full })); }).catch(() => {});
        if (ev.kind === "run") refresh(name, runId);
      }, () => { setLive("off"); refresh(name, runId); }, setLive);
    }).catch(fail);
    return () => { cancelled = true; stop(); };
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Details for the history table's stage mini-graphs (small requests, cached).
  useEffect(() => {
    const missing = runs.filter((r) => !runDetails[r.id]).slice(0, 25);
    if (missing.length === 0) return;
    Promise.all(missing.map((r) => api.run(r.id).catch(() => null))).then((list) => {
      setRunDetails((prev) => { const next = { ...prev }; list.forEach((d) => { if (d) next[d.id] = d; }); return next; });
    });
  }, [runs]); // eslint-disable-line react-hooks/exhaustive-deps

  const lastBuild = useMemo(() => runs.find((r) => r.mode === "build"), [runs]);
  const build = lastBuild ? runDetails[lastBuild.id] : null;
  useEffect(() => {
    if (!lastBuild) { setBuildEvents([]); return; }
    if (lastBuild.id === runId) { setBuildEvents(events); return; }
    api.events(lastBuild.id).then(setBuildEvents).catch(() => {});
  }, [lastBuild?.id, lastBuild?.status, runId, events.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // Stay in sync without a reload: re-fetch when the tab comes back, and poll gently while no
  // live stream is open (a finished run can still change, e.g. repaired after a server restart).
  useEffect(() => {
    const sync = () => { if (document.visibilityState === "visible") refresh(name, runId); };
    window.addEventListener("focus", sync);
    document.addEventListener("visibilitychange", sync);
    const timer = live === "on" ? null : setInterval(sync, 30000);
    return () => { window.removeEventListener("focus", sync); document.removeEventListener("visibilitychange", sync); if (timer) clearInterval(timer); };
  }, [name, runId, live, refresh]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && !modal) setSelected(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modal]);

  const act = async (fn, button) => {
    setError(null);
    try {
      const started = await fn();
      if (started?.id) { setRunId(started.id); setSelected(null); setTab("Pipeline"); }
      await refresh(name, started?.id || runId);
    } catch (e) {
      fail(e);
      if (button) { setShake(button); setTimeout(() => setShake(null), 600); }
    }
  };

  const locked = Boolean(me?.required && !me.login);
  const latest = detail?.latest || {};
  const busy = Boolean(detail?.active_run) || locked;
  const timings = useMemo(() => stepTimings(events), [events]);
  const steps = useMemo(() => detail?.stages.flatMap((s) => s.steps) || [], [detail]);
  const selectedStep = steps.find((s) => s.id === selected) || null;
  const who = run ? requesters[run.id] : null;
  const migration = migrations.find((m) => m.name === name);
  const undoing = run && (run.status === "rolling_back" || run.status === "failed" || run.status === "rollback_failed") && run.completed?.length > 0;
  const rolledBack = run ? Object.values(run.steps || {}).filter((s) => s === "rolled_back").length : 0;
  const rehearsedAndUndone = run?.mode === "rehearse" && run.status === "succeeded";

  const confirmBody = () => {
    if (!modal || !detail) return null;
    const count = steps.length;
    const manual = steps.filter((s) => s.when === "manual").map((s) => s.id);
    if (modal === "rehearse") {
      return (
        <>
          <p>Runs all <b>{count} steps</b> for real in the <b>rehearsal</b> environment (AWS {detail.target.region}, account {maskAccount(detail.target.account)}), then <b>undoes everything</b>. Resources are named <span className="mono">mac-claims-rehearsal-…</span>, so production is never touched.</p>
          {manual.length > 0 && <p>Manual steps will wait for you: <span className="mono">{manual.join(", ")}</span>.</p>}
          <p>If a step fails, AI will <b>{AI_MODES.find(([v]) => v === ai)[1]}</b>: {AI_HELP[ai]}.</p>
          <p className="muted small">Uses the commits locked by Build <span className="mono">#{latest.build?.id}</span>.</p>
        </>
      );
    }
    if (modal === "deploy") {
      const reh = latest.rehearse?.id ? runDetails[latest.rehearse.id] : null;
      const pending = detail.approvals.filter((a) => build?.report?.approvals?.[a.id]?.status !== "approved").map((a) => a.id);
      return (
        <>
          <p>Runs all <b>{count} steps</b> in <b>production</b> (AWS {detail.target.region}, account {maskAccount(detail.target.account)}), with exactly the commits the passing Rehearse used{reh ? ` (#${reh.id})` : ""}:</p>
          {reh && <ul className="mono small">{Object.keys(reh.shas || {}).map((repo) => <li key={repo}>{repo.replace("github.com/", "")} @ {shortSha(repo, reh.shas)}</li>)}</ul>}
          {pending.length > 0 && <p>Deploy will <b>wait</b> at the first step that needs an approval not yet granted: <span className="mono">{pending.join(", ")}</span>. A rejected approval fails the Deploy and undoes everything.</p>}
          {manual.length > 0 && <p>Manual steps will wait for you: <span className="mono">{manual.join(", ")}</span>.</p>}
          <p>If a step fails, AI will <b>{ai === "autofix" ? "Report" : AI_MODES.find(([v]) => v === ai)[1]}</b>{ai === "autofix" && <span className="muted"> (Auto-fix never runs on Deploy)</span>}.</p>
        </>
      );
    }
    if (modal === "undo") {
      return <p>Undoes everything {MODE_LABEL[run.mode]} <span className="mono">#{run.id}</span> did, newest step first{run.mode === "deploy" ? ", destroying the production resources it created" : ""}. Steps that never ran are skipped.</p>;
    }
    return null;
  };

  const confirm = () => {
    const kind = modal;
    setModal(null);
    if (kind === "rehearse") act(() => api.start(name, "rehearse", ai), "rehearse");
    if (kind === "deploy") act(() => api.start(name, "deploy", ai === "autofix" ? "report" : ai), "deploy");
    if (kind === "undo") act(() => api.undo(run.id));
  };

  const reasonVariant = run?.status === "failed" || run?.status === "rollback_failed" ? "danger" : run?.status === "waiting" ? "warning" : "info";

  return (
    <div className="mac">
      <TopBar me={me} live={live} crumbs={["Migrations", detail?.service].filter(Boolean)} />
      <div className="layout">
        <Sidebar migrations={migrations} name={name} detail={detail} open={sidebarOpen} onSelect={(n) => { setSelected(null); setRunId(null); setName(n); setSidebarOpen(false); }} />
        <main className="main">
          <button className="btn btn-sm sidebar-toggle" onClick={() => setSidebarOpen(!sidebarOpen)}>☰ Migrations</button>
          {unreachable && <div className="alert alert-danger">Can't reach the MaC API. <button className="link" onClick={() => { setUnreachable(false); refresh(); }}>Retry</button></div>}
          {error && <div className="alert alert-warning" role="alert">{error}<button className="link" onClick={() => setError(null)}>Dismiss</button></div>}
          {locked && me.available && <div className="alert alert-info">You can watch everything here. To run a pipeline, <a href="/api/auth/login">sign in with GitHub</a> (write access to the repo is required).</div>}

          {migration && !migration.valid && (
            <div className="alert alert-danger">
              <div>
                <b>This migration.yaml can't be run.</b>
                <ul>{migration.problems.map((p) => <li key={p}>{p}</li>)}</ul>
                <span className="small">Fix the file and check it with <span className="mono">mise run mac validate {migration.path}</span>.</span>
              </div>
            </div>
          )}

          {detail && (
            <>
              <div className="page-head">
                <div>
                  <h1>{detail.service}</h1>
                  <div className="page-meta">
                    <span className="mono">{detail.name}</span>
                    <span className="dot" /><span>{detail.target.provider.toUpperCase()} {detail.target.region}</span>
                    <span className="dot" /><span title={detail.target.account}>account {maskAccount(detail.target.account)}</span>
                    <span className="dot" /><span>owner {detail.owner_team}</span>
                    <span className="dot" /><span>{steps.length} steps in {detail.stages.length} stages</span>
                    <span className="dot" /><span>{detail.approvals.length} approvals</span>
                  </div>
                </div>
                <div className="page-actions">
                  <div className="btn-group">
                    <button className={`btn ${shake === "build" ? "shake" : ""}`} disabled={busy} title={locked ? "Sign in to run pipelines" : detail.active_run ? "A run is in progress" : "Checks repos, writes the design page, raises tickets, plans Terraform. Changes nothing in AWS."}
                            onClick={() => act(() => api.start(name, "build"), "build")}>Build</button>
                    <button className={`btn ${shake === "rehearse" ? "shake" : ""}`} disabled={busy || latest.build?.status !== "succeeded"}
                            title={latest.build?.status !== "succeeded" ? "Needs a passing Build of this exact migration.yaml" : "Runs everything in the rehearsal environment, then undoes it"}
                            onClick={() => setModal("rehearse")}>Rehearse</button>
                    <button className={`btn btn-confirm ${shake === "deploy" ? "shake" : ""}`} disabled={busy || latest.rehearse?.status !== "succeeded"}
                            title={latest.rehearse?.status !== "succeeded" ? "Needs a passing Rehearse of this exact migration.yaml" : "Runs everything in production with the rehearsed commits"}
                            onClick={() => setModal("deploy")}>Deploy</button>
                  </div>
                  <div className="ai-setting" title="A setting, not an action: what the AI does if a step fails">
                    <span className="muted small">If a step fails, AI will</span>
                    <div className="segmented" role="radiogroup" aria-label="AI help if a step fails">
                      {AI_MODES.map(([value, label]) => (
                        <button key={value} role="radio" aria-checked={ai === value} className={ai === value ? "on" : ""} onClick={() => setAi(value)} title={AI_HELP[value]}>{label}</button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              <nav className="tabs" role="tablist">
                {TABS.map((t) => (
                  <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
                    {t}{t === "Approvals" && <span className="count">{detail.approvals.length}</span>}{t === "Runs" && <span className="count">{runs.length}</span>}{t === "Jobs" && <span className="count">{steps.length}</span>}
                  </button>
                ))}
              </nav>

              {tab === "Pipeline" && (
                <>
                  {run ? (
                    <section className="run-card">
                      <div className="run-head">
                        <StatusIcon state={run.status} size={28} />
                        <div className="run-title">
                          <div><span className="strong">{MODE_LABEL[run.mode]}</span> <span className="mono">#{run.id}</span> <Badge status={run.status} /></div>
                          <div className="muted small">
                            {timeAgo(run.created)}{who ? <> by <span className="who"><img className="avatar avatar-sm" src={`https://github.com/${who}.png?size=32`} alt="" />{who}</span></> : ""}
                            <span className="dot" />{fmtDuration(runDuration(run))}{run.active && " so far"}
                            {run.based_on && <><span className="dot" />based on&nbsp;<span className="mono">#{run.based_on}</span></>}
                            {run.spec_digest && <><span className="dot" />spec&nbsp;<span className="mono">{run.spec_digest.slice(0, 7)}</span></>}
                            <span className="dot" /><span title={absTime(run.created)}>{absTime(run.created)}</span>
                          </div>
                        </div>
                        <span className="spacer" />
                        {run.status === "waiting" && <button className="btn" disabled={locked} onClick={() => act(() => api.resume(run.id))} title="Ask Jira again and continue">Check approvals</button>}
                        {(run.status === "waiting" || (run.mode === "deploy" && run.status === "succeeded")) && (
                          <button className="btn btn-danger" disabled={locked} onClick={() => setModal("undo")}>Undo</button>
                        )}
                      </div>
                      {run.reason && <div className={`alert alert-${reasonVariant} alert-inline`}><StatusIcon state={run.status} size={14} /> {run.reason}</div>}
                      {undoing && (
                        <div className="rollback-bar" role="status">
                          <StatusIcon state={run.status === "rolling_back" ? "running" : run.status === "rollback_failed" ? "rollback_failed" : "rolled_back"} size={14} />
                          <span>{run.failed_step ? <><span className="mono">{run.failed_step}</span> failed → </> : ""}undoing {run.completed.length} finished step{run.completed.length === 1 ? "" : "s"}, newest first</span>
                          <span className="spacer" />
                          <span className="mono">{rolledBack} / {run.completed.length} undone</span>
                          <span className="rollback-track"><span className="rollback-fill" style={{ width: `${(rolledBack / run.completed.length) * 100}%` }} /></span>
                        </div>
                      )}
                      {rehearsedAndUndone && <div className="alert alert-success alert-inline"><StatusIcon state="succeeded" size={14} /> Rehearsed and undone: every step ran in the rehearsal environment and was then undone, as designed. Deploy is unlocked.</div>}
                      {run.mode === "build" && <div className="muted small build-note">A Build only reads and plans: Terraform steps show their plan, early checks run, nothing changes in AWS.</div>}
                      <PipelineGraph detail={detail} run={run} timings={timings} selected={selected} onSelect={(id) => setSelected(id === selected ? null : id)}
                                     onPlay={(step) => act(() => api.play(run.id, step))} locked={locked} />
                    </section>
                  ) : (
                    <section className="run-card">
                      <div className="empty">No runs yet. <b>Build</b> checks the repos and plans every step without changing anything in AWS.</div>
                      <PipelineGraph detail={detail} run={null} timings={{}} selected={selected} onSelect={(id) => setSelected(id === selected ? null : id)} onPlay={() => {}} locked={locked} />
                    </section>
                  )}

                  {run && <DiagnosisCard run={run} events={events} />}

                  {run && (
                    <div className={`job-area ${selectedStep ? "split" : ""}`}>
                      <JobLog run={run} events={events} step={selected} onShowAll={() => setSelected(null)} />
                      {selectedStep && <JobDetails step={selectedStep} run={run} detail={detail} timing={timings[selected]} events={events} report={build?.report} onPlay={(step) => act(() => api.play(run.id, step))} locked={locked} />}
                    </div>
                  )}
                </>
              )}

              {tab === "Jobs" && (
                <section className="panel">
                  <JobsTable detail={detail} run={run} timings={timings} onSelect={(id) => { setSelected(id); setTab("Pipeline"); }} onPlay={(step) => act(() => api.play(run.id, step))} locked={locked} />
                </section>
              )}

              {tab === "Build report" && (
                <section className="panel">
                  <BuildReport build={build} events={buildEvents} detail={detail} canRehearse={!busy && latest.build?.status === "succeeded"} onRehearse={() => setModal("rehearse")} />
                </section>
              )}

              {tab === "Approvals" && (
                <section className="panel">
                  <ApprovalsTab detail={detail} build={build} run={run} locked={locked} onCheck={() => act(() => api.resume(run.id))} />
                </section>
              )}

              {tab === "Runs" && (
                <section className="panel">
                  <RunsTab runs={runs} details={runDetails} detail={detail} selectedId={runId} requesters={requesters}
                           onSelect={(id) => { setSelected(null); setRunId(id); setTab("Pipeline"); api.run(id).then((full) => { setRun(full); setRunDetails((prev) => ({ ...prev, [id]: full })); }).catch(fail); }} />
                </section>
              )}
            </>
          )}
        </main>
      </div>

      {modal && (
        <Modal title={modal === "rehearse" ? `Rehearse ${detail.service}?` : modal === "deploy" ? `Deploy ${detail.service} to production?` : `Undo ${MODE_LABEL[run.mode]} #${run.id}?`}
               confirmLabel={modal === "rehearse" ? "Rehearse" : modal === "deploy" ? "Deploy to production" : "Undo everything"} danger={modal !== "rehearse"}
               onConfirm={confirm} onCancel={() => setModal(null)}>
          {confirmBody()}
        </Modal>
      )}
    </div>
  );
}
