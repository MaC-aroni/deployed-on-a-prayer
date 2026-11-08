import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bot, Download, ExternalLink, FlaskConical, Hammer, Lock, OctagonX, Pause, Play, RefreshCw, Rocket, RotateCw, Sparkles, Stethoscope, Undo2 } from "lucide-react";
import Menu from "../components/Menu.jsx";
import Dag from "../components/Dag.jsx";
import Endpoints from "../components/Endpoints.jsx";
import FixCard from "../components/FixCard.jsx";
import Markdown from "../components/Markdown.jsx";
import { Confirm, EmptyState, useAuth } from "../components/Shell.jsx";
import { SkeletonPipeline } from "../components/Skeleton.jsx";
import StatusIcon, { Pill } from "../components/StatusIcon.jsx";
import StepInspector from "../components/StepInspector.jsx";
import { api, fmtAgo, fmtTime, follow, reportUrl, repoKey, shortRepo, sourceApi } from "../mac/api.js";
import { useLiveApprovals } from "../mac/useLiveApprovals.js";
import { Link, navigate } from "../router.jsx";
import { MODE_LABEL, STATUS, runMeta } from "../status.js";
import { cx } from "../lib.js";

// The pipeline page. `source` is { kind: "migration", id: name } for a reviewed spec in
// examples/, or { kind: "plan", id: runId } for a plan the Planner generated; both read the
// same shape (docs/api.md, docs/planning-api.md).

const AI_MODES = [
  ["explain", "Explain"],
  ["report", "Report"],
  ["autofix", "Auto-fix"],
];

const ACTIVE = new Set(["running", "waiting", "rolling_back"]);

function aggregate(states) {
  if (!states.length) return "pending";
  for (const p of ["failed", "rollback_failed", "running", "waiting", "blocked", "rolled_back"]) if (states.includes(p)) return p;
  if (states.every((s) => s === "succeeded")) return "succeeded";
  if (states.every((s) => s === "skipped")) return "skipped";
  return "pending";
}

// Two marks at most: the step's state (play, lock, pause, undo) and, when AI touched it, the robot.
function Aside({ step, state, ai }) {
  let mark = null;
  if (state === "waiting") mark = <Play size={14} className="breakpoint-mark" title="Breakpoint: waiting for you to continue" />;
  else if (state === "blocked" || (step.requires_approval?.length && state === "pending")) mark = <Lock size={14} />;
  else if (step.when === "manual") mark = <Pause size={14} className="breakpoint-mark" title="Breakpoint: the pipeline pauses here until someone continues" />;
  else if (state === "failed" || state === "rolled_back") mark = <RotateCw size={14} />;
  return (
    <>
      {mark}
      {ai.length > 0 && <Bot size={15} className="ai-mark" title={`AI assisted: ${ai.join(" · ")}`} />}
    </>
  );
}

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

// Live approval state: the migration detail carries status/detail/checked (the server follows
// Jira); the latest Build's report is the fallback for older servers.
function approvalStatus(mig, reportRun, id) {
  const a = mig?.approvals?.find((x) => x.id === id);
  if (a?.status && a.status !== "not_requested") return { status: a.status, detail: a.detail, checked: a.checked, ticket: a.ticket?.key, url: a.ticket?.url };
  const v = reportRun?.report?.approvals?.[id];
  if (!v) return a?.ticket ? { status: "pending", ticket: a.ticket.key, url: a.ticket.url } : null;
  return typeof v === "string" ? { status: v } : v;
}

export default function Migration({ source, initialRun }) {
  const { locked, health } = useAuth();
  const src = useMemo(() => sourceApi(source), [source.kind, source.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const [mig, setMig] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState(initialRun ?? null);
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [buildRun, setBuildRun] = useState(null);
  const [tab, setTab] = useState("pipeline");
  const [selected, setSelected] = useState(null);
  const [ai, setAi] = useState(null);
  const [toast, setToast] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(null); // "rehearse" | "deploy" | "cancel"
  const [withLogs, setWithLogs] = useState(false);
  const chosen = useRef(Boolean(initialRun));
  const noLlm = health ? !health.llm : false;
  const llmHint = "No LLM is configured here: set MAC_LLM_API_KEY (or NVIDIA_API_KEY) in backend/.env and restart the backend";

  const refresh = useCallback(async () => {
    try {
      const m = await src.detail();
      const rs = await api.runIndex(m.name);
      setMig(m);
      setRuns(rs);
      setLoadError(null);
      setAi((v) => v ?? m.diagnostics_default ?? "explain");
      return { m, rs };
    } catch (e) {
      setLoadError(e);
      return null;
    }
  }, [src]);

  useEffect(() => {
    let alive = true;
    refresh().then((r) => {
      if (!alive || !r || chosen.current) return;
      setRunId(r.m.active_run?.id ?? r.rs[0]?.id ?? null);
    });
    return () => {
      alive = false;
    };
  }, [refresh]);

  // Approvals given in Jira show up within seconds: re-read the migration while any is outstanding.
  const reloadMig = useCallback(() => {
    src.detail().then(setMig).catch(() => {});
  }, [src]);
  useLiveApprovals(mig?.approvals, reloadMig);

  // The latest Build carries guardrail status for the whole migration.
  const latestBuildId = mig?.latest?.build?.id;
  const latestBuildUpdated = mig?.latest?.build?.updated;
  useEffect(() => {
    if (!latestBuildId) return setBuildRun(null);
    api.run(latestBuildId).then(setBuildRun).catch(() => setBuildRun(null));
  }, [latestBuildId, latestBuildUpdated]);

  // Load the selected run and its events; while it's active, follow the stream.
  useEffect(() => {
    if (!runId) {
      setRun(null);
      setEvents([]);
      return;
    }
    let alive = true;
    let stop = () => {};
    (async () => {
      try {
        const [r, evs] = await Promise.all([api.run(runId), api.events(runId)]);
        if (!alive) return;
        setRun(r);
        setEvents(evs);
        if (!r.active) return;
        let fetching = false;
        let again = false;
        const refetchRun = async () => {
          if (fetching) return void (again = true);
          fetching = true;
          do {
            again = false;
            try {
              const nr = await api.run(runId);
              if (alive) setRun(nr);
            } catch {
              /* transient */
            }
          } while (again && alive);
          fetching = false;
        };
        stop = follow(
          runId,
          evs.at(-1)?.seq ?? 0,
          (ev) => {
            if (!alive) return;
            setEvents((prev) => (prev.some((p) => p.seq === ev.seq) ? prev : [...prev, ev]));
            if (ev.kind !== "log") refetchRun();
            if (ev.kind === "log" && /approvals changed in Jira|cancelled by/.test(ev.message)) refresh();
            if (ev.kind === "approval") reloadMig();
          },
          () => {
            if (!alive) return;
            refetchRun();
            refresh();
          },
        );
      } catch (e) {
        if (alive) setToast({ tone: "red", text: e.detail ?? String(e) });
      }
    })();
    return () => {
      alive = false;
      stop();
    };
  }, [runId, refresh, reloadMig]);

  async function act(label, fn) {
    setBusy(true);
    setConfirming(null);
    setActionError(null);
    try {
      const r = await fn();
      setToast({ tone: "green", text: `${label} started` });
      if (r?.id) {
        chosen.current = true;
        setRunId(r.id);
        if (tab === "history") setTab("pipeline");
      }
      await refresh();
    } catch (e) {
      const text = e.detail ?? String(e);
      setToast({ tone: e.status === 409 ? "amber" : e.status === 401 ? "blue" : "red", text });
      setActionError({ label, text, status: e.status });
    } finally {
      setBusy(false);
    }
  }
  const start = (mode) => act(MODE_LABEL[mode], () => src.start(mode, mode === "build" ? {} : { ai }));
  const play = (stepId) => act(`Continue ${stepId}`, () => api.play(run.id, stepId));
  const closeToast = useCallback(() => setToast(null), []);

  const stepsById = useMemo(() => Object.fromEntries((mig?.stages ?? []).flatMap((s) => s.steps.map((st) => [st.id, st]))), [mig]);
  const stateOf = useCallback((id) => run?.steps?.[id] ?? "pending", [run]);

  // Where AI touched a step, and how. Shown as the green robot on the card and listed in the panel.
  const aiOf = useCallback(
    (st) => {
      const out = [];
      if (mig?.source === "generated") out.push("planned by Nemotron");
      if (st.codegen === "llm") out.push("code written by AI, reviewed as a PR");
      const key = repoKey(st.repo);
      if (run?.overrides?.[key]) out.push(`running auto-fix branch ${run.overrides[key]}`);
      if (run?.autofix?.repo && run.autofix.repo === key) out.push(`auto-fix attempt ${run.autofix.attempt ?? "?"}`);
      if (events.some((e) => e.kind === "diagnosis" && e.step === st.id)) out.push("diagnosed by AI after it failed");
      return out;
    },
    [mig?.source, run, events],
  );

  const columns = useMemo(
    () =>
      (mig?.stages ?? []).map((stage) => ({
        id: stage.name,
        name: stage.name,
        status: aggregate(stage.steps.map((s) => stateOf(s.id))),
        steps: stage.steps.map((st) => ({
          id: st.id,
          name: st.id,
          sub: `${st.type} · ${st.entrypoint ?? st.path ?? shortRepo(st.repo)}`,
          status: stateOf(st.id),
          breakpoint: st.when === "manual",
          agent: st.codegen === "llm",
          aside: <Aside step={st} state={stateOf(st.id)} ai={aiOf(st)} />,
        })),
      })),
    [mig, stateOf, aiOf],
  );

  // One chain in the runner's execution order (stages left to right, steps as the API orders
  // them): a step only runs when the one before it finished, and a failure skips the rest.
  // Explicit `needs` that aren't the immediate predecessor are drawn too.
  const edges = useMemo(() => {
    const order = (mig?.stages ?? []).flatMap((s) => s.steps);
    const out = order.slice(1).map((st, i) => ({ from: order[i].id, to: st.id }));
    order.forEach((st, i) => {
      for (const n of st.needs ?? []) if (i === 0 || n !== order[i - 1].id) out.push({ from: n, to: st.id });
    });
    return out;
  }, [mig]);

  if (loadError) {
    return (
      <EmptyState title={loadError.status === 404 ? `Nothing at ${source.id}` : "Backend unreachable"} body={loadError.detail}>
        <p className="muted small">The runner API is at /api/mac. Locally, start it with `mise run dev-local`.</p>
      </EmptyState>
    );
  }
  if (!mig) return <SkeletonPipeline />;

  const active = Boolean(mig.active_run);
  const canRehearse = mig.latest?.build?.status === "succeeded" && !active;
  const canDeploy = mig.latest?.rehearse?.status === "succeeded" && !active;
  const rm = run ? runMeta(run.status, run.mode) : runMeta("none");
  const reportRun = run?.mode === "build" ? run : buildRun;
  const step = selected ? stepsById[selected] : null;
  const activity = withLogs ? events : events.filter((e) => e.kind !== "log");
  const openApprovals = mig.approvals.filter((a) => approvalStatus(mig, reportRun, a.id)?.status !== "approved").length;
  const generated = mig.source === "generated";
  const runActive = Boolean(run && ACTIVE.has(run.status));
  const waitingStep = run?.status === "waiting" ? Object.entries(run.steps ?? {}).find(([, st]) => st === "waiting")?.[0] : null;
  const broke = run && !run.active && (run.status === "failed" || run.status === "rollback_failed") && run.failed_step;
  const investigation = broke ? runs.find((r) => r.mode === "diagnose" && r.based_on === run.id) : null;
  const diagnoses = events.filter((e) => e.kind === "diagnosis");
  const canUndo = run && !run.active && run.mode !== "build" && (run.status === "waiting" || (run.mode === "deploy" && run.status === "succeeded") || run.status === "rollback_failed");
  const investigate = () =>
    act("Investigation", async () => {
      const r = await api.investigate(run.id, ai);
      navigate(`/agents/${r.id}`);
      return null;
    });
  const primary = waitingStep
    ? { label: `Continue · ${waitingStep}`, icon: <Play size={14} />, onClick: () => play(waitingStep), title: "Breakpoint: the pipeline waits here until you continue" }
    : broke && !investigation
      ? { label: "Investigate", icon: <Stethoscope size={14} />, onClick: investigate, disabled: noLlm, title: noLlm ? llmHint : "Launch the Diagnostician: root cause, proposed fix, approval ticket" }
      : canDeploy
        ? { label: "Deploy", icon: <Rocket size={14} />, onClick: () => setConfirming("deploy"), title: "Run in production with the rehearsed commits" }
        : canRehearse
          ? { label: "Rehearse", icon: <FlaskConical size={14} />, onClick: () => setConfirming("rehearse"), title: "Run everything in the rehearsal environment, then undo it" }
          : active
            ? null
            : { label: "Build", icon: <Hammer size={14} />, onClick: () => start("build"), title: "Validate, lock commits, check guardrails, raise approvals, plan" };

  const confirmText =
    confirming === "cancel"
      ? `Stop ${MODE_LABEL[run?.mode] ?? "this run"} ${run?.id ?? ""} and undo everything it did? A running script is stopped; a running Terraform command finishes first.`
      : `${MODE_LABEL[confirming]} ${mig.service}? This changes real AWS${confirming === "rehearse" ? " (rehearsal environment, undone at the end)" : " in production"}.`;
  const onConfirm = () => (confirming === "cancel" ? act("Cancel", () => api.cancel(run.id)) : start(confirming));

  return (
    <>
      <Toast toast={toast} onClose={closeToast} />

      <div className="run-head">
        <div className="run-head-main">
          <Pill tone={rm.tone} className="pill-lg">
            {run ? `${MODE_LABEL[run.mode]} · ${rm.label}` : rm.label}
          </Pill>
          <h1>
            {mig.service} <span className="muted">→ {mig.target.provider.toUpperCase()}</span>
          </h1>
          <div className="run-meta">
            <span>{mig.name}</span>
            <span>{mig.owner_team}</span>
            <span>
              {mig.target.account} · {mig.target.region}
            </span>
            {generated ? (
              <Link to={`/migrate/${mig.plan_run}`} className="link" title="Open the planning run">
                <Sparkles size={12} /> planned by Nemotron
              </Link>
            ) : (
              <span className="faint">reviewed spec</span>
            )}
            {mig.pr_url && (
              <a className="link" href={mig.pr_url} target="_blank" rel="noreferrer">
                pull request <ExternalLink size={11} />
              </a>
            )}
            {run && (
              <span>
                run {run.id} · {fmtTime(run.created)}
              </span>
            )}
            {run?.active && (
              <span className="live">
                <span className="live-dot" /> live
              </span>
            )}
            {run?.reason && (
              <span className="run-reason" title={run.reason}>
                {run.reason}
              </span>
            )}
          </div>
        </div>
        <div className="run-actions">
          <div className="actions-row">
            {primary && (
              <button className={cx("btn btn-primary", { hint: locked })} onClick={primary.onClick} disabled={busy || primary.disabled} title={primary.title}>
                {primary.icon} {primary.label}
              </button>
            )}
            <Menu
              items={[
                { heading: "Actions" },
                { label: "Build", detail: "validate · lock · guardrails · plan", icon: <Hammer size={14} />, onClick: () => start("build") },
                { label: "Rehearse", detail: canRehearse ? "rehearsal env, undone after" : "needs a passing Build", hint: !canRehearse, icon: <FlaskConical size={14} />, onClick: () => setConfirming("rehearse") },
                { label: "Deploy", detail: canDeploy ? "production" : "needs a passing Rehearse", hint: !canDeploy, icon: <Rocket size={14} />, onClick: () => setConfirming("deploy") },
                ...(mig.approvals.length ? [{ label: "Sync with Jira", detail: mig.approvals_live ? "the server follows Jira already; ask it now" : "ask Jira about every open approval", icon: <RefreshCw size={14} />, onClick: () => act("Jira sync", () => api.approvalsSync(mig.name).then(() => null)) }] : []),
                ...(broke ? [{ label: investigation ? "Investigate again" : "Investigate", detail: noLlm ? "no LLM configured here" : `Diagnostician on ${run.failed_step}`, hint: noLlm, icon: <Stethoscope size={14} />, onClick: investigate }] : []),
                ...(run?.ai_report ? [{ label: "Download AI report", detail: "report.md for a coding agent", icon: <Download size={14} />, onClick: () => window.open(reportUrl(run.id), "_blank") }] : []),
                ...(runActive ? [{ label: "Cancel this run", detail: "stop, then undo everything it did", danger: true, icon: <OctagonX size={14} />, onClick: () => setConfirming("cancel") }] : []),
                ...(canUndo ? [{ label: run.status === "rollback_failed" ? "Retry undo" : "Undo this run", detail: run.status === "rollback_failed" ? "only what wasn't undone" : "undo everything it did", danger: true, icon: <Undo2 size={14} />, onClick: () => act("Undo", () => api.undo(run.id)) }] : []),
              ]}
              footer={
                <>
                  <div className="menu-sep" />
                  <div className="menu-heading">If a step fails, AI will</div>
                </>
              }
            >
              <div className="segmented" title="If a step fails, AI will">
                {AI_MODES.map(([id, label]) => (
                  <button key={id} className={cx("seg", { active: ai === id })} onClick={() => setAi(id)}>
                    {label}
                  </button>
                ))}
              </div>
            </Menu>
          </div>
          {actionError && (
            <div className={cx("action-error", { soft: actionError.status === 409 })} role="alert" onClick={() => setActionError(null)}>
              <strong>{actionError.label} didn't start.</strong> {actionError.text}
            </div>
          )}
          {confirming && <Confirm text={confirmText} onYes={onConfirm} onNo={() => setConfirming(null)} busy={busy} />}
        </div>
      </div>

      {run?.autofix?.branch && (
        <div className="autofix-strip">
          <Bot size={14} className="ai-mark" />
          <span>
            <strong>Auto-fix attempt {run.autofix.attempt ?? "?"} of 3</strong> on branch <span className="mono">{run.autofix.branch}</span>
            {run.autofix.repo && <span className="muted"> · {shortRepo(run.autofix.repo)}</span>}
          </span>
          {run.autofix.parent && (
            <Link to={`/migrations/${encodeURIComponent(mig.name)}?run=${run.autofix.parent}`} className="link">
              failed run {run.autofix.parent}
            </Link>
          )}
          {run.autofix.pr && (
            <a className="link" href={run.autofix.pr} target="_blank" rel="noreferrer">
              pull request <ExternalLink size={11} />
            </a>
          )}
        </div>
      )}

      <div className="tabs">
        {[
          ["pipeline", "Pipeline"],
          ["approvals", "Approvals", openApprovals ? `${openApprovals} open` : mig.approvals.length],
          ["endpoints", "Endpoints", mig.endpoints?.length || null],
          ["report", "Build report"],
          ["activity", "Activity", activity.length || null],
          ["history", "History", runs.length || null],
        ].map(([key, label, count]) => (
          <button key={key} className={cx("tab", { active: tab === key })} onClick={() => setTab(key)}>
            {label}
            {count != null && <span className="count">{count}</span>}
          </button>
        ))}
      </div>

      {tab === "pipeline" && (
        <div className="tab-panel" key="pipeline">
          <div className="dag-frame">
            <Dag columns={columns} edges={edges} selectedId={selected} onSelect={(id) => setSelected(id === selected ? null : id)} failedId={run?.failed_step ?? null} onAgent={() => run && navigate(`/agents/${run.id}`)} />
          </div>

          {broke && (diagnoses.length > 0 || investigation) && (
            <FailureCard run={run} diagnoses={diagnoses} investigation={investigation} onChanged={refresh} locked={locked} />
          )}

          {step && <StepInspector step={step} state={stateOf(step.id)} run={run} events={events} approvals={mig.approvals} report={reportRun?.report} onPlay={play} onClose={() => setSelected(null)} busy={busy || locked} ai={aiOf(step)} />}
        </div>
      )}

      {tab === "approvals" && (
        <div className="tab-panel" key="approvals">
          <div className="toolbar">
            <span className="muted small">
              {mig.approvals_live ? "The server follows Jira on its own" : "Jira is polled only on Build and Deploy here"}
              {mig.approvals_checked ? ` · last checked ${fmtAgo(mig.approvals_checked)}` : ""}
            </span>
            <span className="spacer" />
            {mig.approvals.length > 0 && (
              <button className={cx("btn", { hint: locked })} onClick={() => act("Jira sync", () => api.approvalsSync(mig.name).then(() => null))} disabled={busy}>
                <RefreshCw size={14} /> Sync with Jira
              </button>
            )}
          </div>
          <div className="cards">
            {mig.approvals.map((a) => {
              const st = approvalStatus(mig, reportRun, a.id);
              const status = st?.status ?? "not_requested";
              const ticketUrl = a.ticket?.url ?? st?.url;
              const ticketKey = a.ticket?.key ?? st?.ticket;
              const open = () => ticketUrl && window.open(ticketUrl, "_blank", "noopener");
              return (
                <article className={cx("card", { "card-btn": Boolean(ticketUrl) })} key={a.id} onClick={open} role={ticketUrl ? "button" : undefined} tabIndex={ticketUrl ? 0 : undefined} onKeyDown={(e) => e.key === "Enter" && open()}>
                  <header className="card-head">
                    <StatusIcon status={status === "pending" || status === "not_requested" ? "blocked" : status} size={22} />
                    <div className="card-title">
                      <strong className="mono">{a.id}</strong>
                      <span className="muted">{a.type.replaceAll("_", " ")}</span>
                    </div>
                    <Pill tone={STATUS[status]?.tone ?? "grey"}>{status === "pending" ? "Pending" : status === "not_requested" ? "Not raised yet" : (STATUS[status]?.label ?? status)}</Pill>
                  </header>
                  <strong className="card-summary">{a.summary}</strong>
                  <p className="card-body">{a.justification}</p>
                  <footer className="card-foot">
                    <span>
                      approver <span className="mono">{a.approver}</span>
                    </span>
                    {ticketKey ? (
                      <a className="link mono" href={ticketUrl ?? "#"} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                        {ticketKey} <ExternalLink size={11} />
                      </a>
                    ) : (
                      <span className="muted">ticket not raised yet</span>
                    )}
                    {a.after?.length > 0 && (
                      <span>
                        after <span className="mono">{a.after.join(", ")}</span>
                      </span>
                    )}
                    {a.design_doc && <Pill tone="violet">design page</Pill>}
                    {st?.detail && <span className="muted">{st.detail}</span>}
                    {st?.checked && <span className="faint small">checked {fmtAgo(st.checked)}</span>}
                  </footer>
                </article>
              );
            })}
          </div>
        </div>
      )}

      {tab === "endpoints" && (
        <div className="tab-panel" key="endpoints">
          <Endpoints endpoints={mig.endpoints ?? []} run={run} />
        </div>
      )}

      {tab === "report" && (
        <div className="tab-panel" key="report">
          <BuildReport run={reportRun} mig={mig} />
        </div>
      )}

      {tab === "activity" && (
        <div className="tab-panel" key="activity">
          <div className="toolbar">
            <button className="btn" onClick={() => setWithLogs((v) => !v)}>
              {withLogs ? "Hide log lines" : "Include log lines"}
            </button>
            {run && (
              <span className="muted small">
                {MODE_LABEL[run.mode]} {run.id}
              </span>
            )}
          </div>
          {activity.length === 0 ? (
            <EmptyState title="No activity yet" body={run ? "The runner hasn't reported anything for this run." : "Select a run or press Build."} />
          ) : (
            <ol className="feed-lines">
              {activity.map((e) => (
                <li key={e.seq} className={cx("feed-line", `k-${e.kind}`)}>
                  <span className="mono small muted">{fmtTime(e.ts)}</span>
                  <span className={cx("kind", `kind-${e.kind}`)}>{e.kind}</span>
                  <span className="mono small">{e.step ?? ""}</span>
                  <span className="msg">{e.kind === "diagnosis" ? <Markdown text={e.message} className="markdown markdown-inline" /> : e.message}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {tab === "history" && (
        <div className="table runs-table tab-panel" key="history">
          <p className="muted small" style={{ padding: "8px 28px 4px" }}>
            Click a run to show it on the pipeline. {run ? `Showing ${MODE_LABEL[run.mode]} ${run.id}.` : ""}
          </p>
          <div className="tr th">
            <div>Status</div>
            <div>Run</div>
            <div>Reason</div>
            <div>Started</div>
            <div>Updated</div>
          </div>
          {runs.map((r) => {
            const m = runMeta(r.status, r.mode);
            return (
              <button
                type="button"
                key={r.id}
                className={cx("tr row-btn", { selected: r.id === runId })}
                onClick={() => {
                  if (r.mode === "diagnose") return navigate(`/agents/${r.id}`);
                  chosen.current = true;
                  setRunId(r.id);
                  setTab("pipeline");
                }}
              >
                <div>
                  <Pill tone={m.tone}>
                    <StatusIcon status={m.icon} size={14} />
                    {m.label}
                  </Pill>
                </div>
                <div>
                  <span className="row-title">{MODE_LABEL[r.mode]}</span>
                  <span className="mono small muted">{r.id}</span>
                </div>
                <div className="small reason" title={r.reason ?? ""}>
                  {r.reason ?? (r.failed_step ? `failed at ${r.failed_step}` : "—")}
                </div>
                <div className="small">
                  {fmtTime(r.created)} <span className="muted">· {fmtAgo(r.created)}</span>
                </div>
                <div className="small">{fmtTime(r.updated)}</div>
              </button>
            );
          })}
          {runs.length === 0 && <div className="tr empty-row">No runs yet. Press Build.</div>}
        </div>
      )}
    </>
  );
}

// One story for a failure: the runner's own AI help (diagnosis events, Markdown) and, when a
// person launched it, the Diagnostician's structured result with Approve fix. Both in one place.
function FailureCard({ run, diagnoses, investigation, onChanged, locked }) {
  const [diag, setDiag] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const id = investigation?.id;
  useEffect(() => {
    if (!id) return setDiag(null);
    let alive = true;
    let stop = () => {};
    api
      .run(id)
      .then((r) => {
        if (!alive) return;
        setDiag(r);
        if (r.active) stop = follow(id, 0, () => {}, () => alive && api.run(id).then((nr) => alive && (setDiag(nr), onChanged())).catch(() => {}));
      })
      .catch(() => {});
    return () => {
      alive = false;
      stop();
    };
  }, [id, onChanged]);
  async function approve() {
    setBusy(true);
    setErr(null);
    try {
      setDiag(await api.approveFix(id));
    } catch (e) {
      setErr(e.detail ?? String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="failure-card">
      {diagnoses.length > 0 && (
        <article className="card diagnosis-card">
          <header className="card-head">
            <div className="card-title">
              <strong>
                <Bot size={14} className="ai-mark" /> AI help · {run.diagnostics_mode ?? "explain"}
              </strong>
              <span className="muted">what the runner's diagnostician said when {run.failed_step} failed</span>
            </div>
            {run.ai_report && (
              <a className="btn" href={reportUrl(run.id)} target="_blank" rel="noreferrer">
                <Download size={14} /> Download report
              </a>
            )}
          </header>
          {diagnoses.map((d) => (
            <Markdown key={d.seq} text={d.message} />
          ))}
        </article>
      )}
      {diag && <FixCard run={diag} onApprove={approve} busy={busy} locked={locked} />}
      {id && (
        <div className="toolbar" style={{ marginTop: 8 }}>
          <Link to={`/agents/${id}`} className="link">
            <Bot size={13} /> Open the agent view
          </Link>
          {err && <span className="small" style={{ color: "var(--bad)" }}>{err}</span>}
        </div>
      )}
    </div>
  );
}

function BuildReport({ run, mig }) {
  if (!run) return <EmptyState title="No Build yet" body="Build validates the spec, locks commits, checks guardrails on GitHub, raises approvals and plans Terraform." />;
  const rep = run.report ?? {};
  const guardrails = rep.guardrails ?? {};
  const approvals = rep.approvals ?? {};
  const m = runMeta(run.status, run.mode);
  return (
    <div className="report">
      <div className="report-head">
        <Pill tone={m.tone}>
          <StatusIcon status={m.icon} size={14} /> Build {m.label}
        </Pill>
        <span className="mono small muted">
          {run.id} · {fmtTime(run.created)}
        </span>
        {run.reason && <span className="small">{run.reason}</span>}
      </div>

      {rep.issues?.length > 0 && (
        <section className="report-section">
          <h3>Issues</h3>
          <ul className="plain">
            {rep.issues.map((i, k) => (
              <li key={k}>{typeof i === "string" ? i : JSON.stringify(i)}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="report-section">
        <h3>Locked commits</h3>
        {Object.keys(run.shas ?? {}).length === 0 ? (
          <p className="muted small">none yet</p>
        ) : (
          <table className="report-table">
            <tbody>
              {Object.entries(run.shas).map(([repo, sha]) => (
                <tr key={repo}>
                  <td className="mono">{shortRepo(repo)}</td>
                  <td className="mono muted">{sha.slice(0, 12)}</td>
                  <td className="muted">{run.overrides?.[repo] ? <span className="ai-badge"><Bot size={11} /> auto-fix branch {run.overrides[repo]}</span> : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="report-section">
        <h3>Guardrails</h3>
        {Object.keys(guardrails).length === 0 ? (
          <p className="muted small">not checked yet</p>
        ) : (
          <table className="report-table">
            <tbody>
              {Object.entries(guardrails).map(([repo, checks]) =>
                (checks ?? []).map((c, i) => (
                  <tr key={`${repo}-${c.name}`}>
                    {i === 0 && (
                      <td className="mono" rowSpan={checks.length}>
                        {shortRepo(repo)}
                      </td>
                    )}
                    <td>
                      <StatusIcon status={c.passed ? "succeeded" : "failed"} size={16} />
                    </td>
                    <td className="mono">{c.name}</td>
                    <td className="muted">{c.detail}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        )}
      </section>

      <section className="report-section">
        <h3>Approvals</h3>
        <table className="report-table">
          <tbody>
            {mig.approvals.map((a) => {
              const live = approvalStatus(mig, run, a.id);
              const v = approvals[a.id];
              const st = live ?? (typeof v === "string" ? { status: v } : (v ?? { status: "unknown" }));
              return (
                <tr key={a.id}>
                  <td>
                    <StatusIcon status={st.status === "pending" ? "blocked" : st.status} size={16} />
                  </td>
                  <td className="mono">{a.id}</td>
                  <td>{a.approver}</td>
                  <td className="mono">
                    {st.url ? (
                      <a href={st.url} target="_blank" rel="noreferrer">
                        {st.ticket}
                      </a>
                    ) : (
                      (st.ticket ?? "—")
                    )}
                  </td>
                  <td className="muted">{st.detail ?? ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="report-section">
        <h3>Design page</h3>
        {rep.design_page?.url || mig.design_page?.url ? (
          <p>
            <a className="link" href={rep.design_page?.url ?? mig.design_page.url} target="_blank" rel="noreferrer">
              Open in Confluence <ExternalLink size={11} />
            </a>{" "}
            <span className="muted small">{rep.design_page?.status ?? (mig.design_page?.current ? "current" : "spec changed since it was written")}</span>
          </p>
        ) : (
          <p className="muted small">not written yet (needs the LLM and Confluence configured; Build passes without it)</p>
        )}
      </section>
    </div>
  );
}
