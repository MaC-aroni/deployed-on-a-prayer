import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bot, Cloud, ExternalLink, FlaskConical, Hammer, Hand, Lock, Play, Rocket, RotateCw, Sparkles, Undo2, Users } from "lucide-react";
import Dag from "../components/Dag.jsx";
import { Confirm, EmptyState, useAuth } from "../components/Shell.jsx";
import StatusIcon, { Pill } from "../components/StatusIcon.jsx";
import StepInspector from "../components/StepInspector.jsx";
import { api, fmtAgo, fmtTime, follow, shortRepo, sourceApi } from "../mac/api.js";
import { Link } from "../router.jsx";
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

function aggregate(states) {
  if (!states.length) return "pending";
  for (const p of ["failed", "rollback_failed", "running", "waiting", "blocked", "rolled_back"]) if (states.includes(p)) return p;
  if (states.every((s) => s === "succeeded")) return "succeeded";
  if (states.every((s) => s === "skipped")) return "skipped";
  return "pending";
}

function Aside({ step, state }) {
  if (state === "waiting") return <Play size={14} className="nemotron" />;
  if (step.codegen === "llm") return <Bot size={14} className="nemotron" title="AI writes this step" />;
  if (state === "blocked" || (step.requires_approval?.length && state === "pending")) return <Lock size={14} />;
  if (step.when === "manual") return <Hand size={14} />;
  if (state === "failed" || state === "rolled_back") return <RotateCw size={14} />;
  return null;
}

function Toggle({ checked, onChange, label }) {
  return (
    <label className="toggle-row">
      <span>{label}</span>
      <button type="button" role="switch" aria-checked={checked} className={cx("toggle", { on: checked })} onClick={() => onChange(!checked)}>
        <span className="toggle-knob" />
      </button>
    </label>
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

function approvalStatus(reportRun, id) {
  const v = reportRun?.report?.approvals?.[id];
  if (!v) return null;
  return typeof v === "string" ? { status: v } : v;
}

export default function Migration({ source, initialRun }) {
  const { locked } = useAuth();
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
  const [showDeps, setShowDeps] = useState(true);
  const [fit, setFit] = useState(true);
  const [ai, setAi] = useState(null);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(null); // "rehearse" | "deploy"
  const [withLogs, setWithLogs] = useState(false);
  const chosen = useRef(Boolean(initialRun));

  const refresh = useCallback(async () => {
    try {
      const m = await src.detail();
      const rs = await api.runs(m.name);
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

  // The latest Build carries approval and guardrail status for the whole migration.
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
  }, [runId, refresh]);

  async function act(label, fn) {
    setBusy(true);
    setConfirming(null);
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
      setToast({ tone: e.status === 409 ? "amber" : e.status === 401 ? "blue" : "red", text: e.detail ?? String(e) });
    } finally {
      setBusy(false);
    }
  }
  const start = (mode) => act(MODE_LABEL[mode], () => src.start(mode, mode === "build" ? {} : { ai }));
  const play = (stepId) => act(`Play ${stepId}`, () => api.play(run.id, stepId));
  const closeToast = useCallback(() => setToast(null), []);

  const stepsById = useMemo(() => Object.fromEntries((mig?.stages ?? []).flatMap((s) => s.steps.map((st) => [st.id, st]))), [mig]);
  const stateOf = useCallback((id) => run?.steps?.[id] ?? "pending", [run]);

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
          aside: <Aside step={st} state={stateOf(st.id)} />,
        })),
      })),
    [mig, stateOf],
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
  if (!mig) return <EmptyState title="Loading…" />;

  const active = Boolean(mig.active_run);
  const canRehearse = mig.latest?.build?.status === "succeeded" && !active;
  const canDeploy = mig.latest?.rehearse?.status === "succeeded" && !active;
  const rm = run ? runMeta(run.status, run.mode) : runMeta("none");
  const reportRun = run?.mode === "build" ? run : buildRun;
  const step = selected ? stepsById[selected] : null;
  const activity = withLogs ? events : events.filter((e) => e.kind !== "log");
  const openApprovals = mig.approvals.filter((a) => approvalStatus(reportRun, a.id)?.status !== "approved").length;
  const generated = mig.source === "generated";

  return (
    <>
      <Toast toast={toast} onClose={closeToast} />

      <div className="run-head">
        <div className="run-head-main">
          <div className="pill-row">
            <Pill tone={rm.tone} className="pill-lg">
              <StatusIcon status={rm.icon} size={16} />
              {run ? `${MODE_LABEL[run.mode]} · ${rm.label}` : rm.label}
            </Pill>
            {generated ? (
              <Link to={`/migrate/${mig.plan_run}`} className="pill tone-violet pill-link" title="Open the planning run">
                <Sparkles size={13} /> Planned by Nemotron
              </Link>
            ) : (
              <Pill tone="grey">reviewed spec</Pill>
            )}
          </div>
          <h1>
            {mig.service} <span className="muted">→ {mig.target.provider.toUpperCase()}</span>
          </h1>
          <div className="run-meta">
            <span className="mono">{mig.name}</span>
            <span>
              <Users size={13} /> {mig.owner_team}
            </span>
            <span>
              <Cloud size={13} /> {mig.target.account} · {mig.target.region}
            </span>
            {mig.pr_url && (
              <a className="link" href={mig.pr_url} target="_blank" rel="noreferrer">
                pull request <ExternalLink size={11} />
              </a>
            )}
            {run && (
              <span className="mono">
                run {run.id} · {fmtTime(run.created)}
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
            <div className="segmented" title="If a step fails, AI will">
              <Sparkles size={13} className="nemotron seg-icon" />
              {AI_MODES.map(([id, label]) => (
                <button key={id} className={cx("seg", { active: ai === id })} onClick={() => setAi(id)}>
                  {label}
                </button>
              ))}
            </div>
            <button className={cx("btn btn-primary", { hint: locked })} onClick={() => start("build")} disabled={busy} title="Validate, lock commits, check guardrails, raise approvals, plan">
              <Hammer size={14} /> Build
            </button>
            <button className={cx("btn", { hint: !canRehearse || locked })} onClick={() => setConfirming("rehearse")} disabled={busy} title={canRehearse ? "Run everything in the rehearsal environment, then undo it" : "Needs a passing Build of this exact migration.yaml"}>
              <FlaskConical size={14} /> Rehearse
            </button>
            <button className={cx("btn", { hint: !canDeploy || locked })} onClick={() => setConfirming("deploy")} disabled={busy} title={canDeploy ? "Run in production with the rehearsed commits" : "Needs a passing Rehearse of this exact migration.yaml"}>
              <Rocket size={14} /> Deploy
            </button>
            {run?.status === "waiting" && (
              <button className={cx("btn", { hint: locked })} onClick={() => act("Check approvals", () => api.resume(run.id))} disabled={busy} title="Check the approvals again">
                <Play size={14} /> Check approvals
              </button>
            )}
            {run && (run.status === "waiting" || (run.mode === "deploy" && run.status === "succeeded")) && (
              <button className={cx("btn", { hint: locked })} onClick={() => act("Undo", () => api.undo(run.id))} disabled={busy}>
                <Undo2 size={14} /> Undo
              </button>
            )}
          </div>
          {confirming && (
            <Confirm
              text={`${MODE_LABEL[confirming]} ${mig.service}? This changes real AWS${confirming === "rehearse" ? " (rehearsal environment, undone at the end)" : " in production"}.`}
              onYes={() => start(confirming)}
              onNo={() => setConfirming(null)}
              busy={busy}
            />
          )}
        </div>
      </div>

      <div className="tabs">
        {[
          ["pipeline", "Pipeline"],
          ["approvals", "Approvals", openApprovals ? `${openApprovals} open` : mig.approvals.length],
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
        <>
          <div className="toolbar pipeline-toolbar">
            <label className="run-picker">
              <span className="muted small">Run</span>
              <select
                value={runId ?? ""}
                onChange={(e) => {
                  chosen.current = true;
                  setRunId(e.target.value || null);
                }}
              >
                {!runs.length && <option value="">no runs yet</option>}
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    {MODE_LABEL[r.mode]} · {runMeta(r.status, r.mode).label} · {fmtTime(r.created)}
                  </option>
                ))}
              </select>
            </label>
            <Toggle label="Show flow" checked={showDeps} onChange={setShowDeps} />
            <Toggle label="Fit to width" checked={fit} onChange={setFit} />
            {run?.active && (
              <span className="live">
                <span className="live-dot" /> live
              </span>
            )}
          </div>

          <div className="dag-frame">
            <Dag columns={columns} edges={edges} selectedId={selected} onSelect={(id) => setSelected(id === selected ? null : id)} showDeps={showDeps} fit={fit} />
          </div>

          {step && <StepInspector step={step} state={stateOf(step.id)} run={run} events={events} approvals={mig.approvals} report={reportRun?.report} onPlay={play} onClose={() => setSelected(null)} busy={busy || locked} />}
        </>
      )}

      {tab === "approvals" && (
        <div className="cards">
          {mig.approvals.map((a) => {
            const st = approvalStatus(reportRun, a.id);
            const status = st?.status ?? "unknown";
            const ticketUrl = a.ticket?.url ?? st?.url;
            const ticketKey = a.ticket?.key ?? st?.ticket;
            return (
              <article className="card" key={a.id}>
                <header className="card-head">
                  <StatusIcon status={status === "pending" ? "blocked" : status} size={22} />
                  <div className="card-title">
                    <strong className="mono">{a.id}</strong>
                    <span className="muted">{a.type.replaceAll("_", " ")}</span>
                  </div>
                  <Pill tone={STATUS[status]?.tone ?? "grey"}>{status === "pending" ? "Pending" : STATUS[status]?.label ?? status}</Pill>
                </header>
                <strong className="card-summary">{a.summary}</strong>
                <p className="card-body">{a.justification}</p>
                <footer className="card-foot">
                  <span>
                    approver <span className="mono">{a.approver}</span>
                  </span>
                  {ticketKey ? (
                    <a className="link mono" href={ticketUrl ?? "#"} target="_blank" rel="noreferrer">
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
                </footer>
              </article>
            );
          })}
        </div>
      )}

      {tab === "report" && <BuildReport run={reportRun} mig={mig} />}

      {tab === "activity" && (
        <>
          <div className="toolbar">
            <Toggle label="Include log lines" checked={withLogs} onChange={setWithLogs} />
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
                  <span className="msg">{e.message}</span>
                </li>
              ))}
            </ol>
          )}
        </>
      )}

      {tab === "history" && (
        <div className="table runs-table">
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
              const v = approvals[a.id];
              const st = typeof v === "string" ? { status: v } : (v ?? { status: "unknown" });
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
