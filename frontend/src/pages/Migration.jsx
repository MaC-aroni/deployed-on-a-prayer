import { useEffect, useMemo, useState } from "react";
import { ExternalLink, GitBranch, GitPullRequest, Pause, Play, Sparkles, Timer } from "lucide-react";
import Dag from "../components/Dag.jsx";
import NodeDrawer from "../components/NodeDrawer.jsx";
import StatusIcon, { Pill } from "../components/StatusIcon.jsx";
import { EmptyState } from "../components/Shell.jsx";
import { APPROVALS, NOW, RUN, RUN_STATUS, STAGES, STATUS, STEPS, STEP_BY_ID, TRACES, durationAt, runStatusAt, statusAt } from "../data/mock.js";
import { cx, fmtClock, fmtDuration } from "../lib.js";

// Replay walks through the run's key moments at an even pace, so the long
// human waits (approvals, merge) don't eat the whole playback.
function useReplay() {
  const keys = useMemo(() => {
    const set = new Set([0, NOW]);
    for (const s of STEPS) for (const k of [s.start, s.gateUntil, s.end, s.rollbackAt]) if (k != null) set.add(k);
    return [...set].sort((a, b) => a - b);
  }, []);
  const [p, setP] = useState(1); // 0..1 progress along the key timeline
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing) return;
    let raf;
    let last = performance.now();
    const perMs = 1 / 16000; // whole run in ~16s
    const tick = (now) => {
      const dt = now - last;
      last = now;
      setP((prev) => {
        const next = prev + dt * perMs;
        if (next >= 1) {
          setPlaying(false);
          return 1;
        }
        return next;
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const t = useMemo(() => {
    const segs = keys.length - 1;
    const pos = Math.min(Math.max(p, 0), 1) * segs;
    const i = Math.min(Math.floor(pos), segs - 1);
    const frac = pos - i;
    return keys[i] + (keys[i + 1] - keys[i]) * frac;
  }, [p, keys]);

  function toggle() {
    if (playing) return setPlaying(false);
    if (p >= 1) setP(0);
    setPlaying(true);
  }
  return { t, p, setP, playing, toggle };
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

export default function Migration({ id }) {
  const [tab, setTab] = useState("pipeline");
  const [selected, setSelected] = useState("diagnose");
  const [showDeps, setShowDeps] = useState(true);
  const [fit, setFit] = useState(true);
  const replay = useReplay();
  const t = replay.t;

  if (String(id) !== String(RUN.id)) {
    return <EmptyState title={`Migration #${id}`} body="Run detail is mocked for #142 only. The others will load from /api once the runner reports state." />;
  }

  const status = runStatusAt(t);
  const rs = RUN_STATUS[status];
  const step = selected ? STEP_BY_ID[selected] : null;
  const approvalsOpen = APPROVALS.filter((a) => statusAt(STEP_BY_ID[a.stepId], t) !== "approved").length;

  return (
    <>
      <div className="run-head">
        <div className="run-head-main">
          <Pill tone={rs.tone} className="pill-lg">
            <StatusIcon status={status === "passed" ? "succeeded" : status === "recovering" ? "running" : status} size={16} agent={status === "recovering"} />
            {rs.label}
          </Pill>
          <h1>{RUN.title}</h1>
          <div className="run-meta">
            <span className="mono">#{RUN.id}</span>
            <span>
              <GitBranch size={13} /> {RUN.branch}
            </span>
            <span>
              <GitPullRequest size={13} /> !{RUN.pr}
            </span>
            <span>
              <Sparkles size={13} className="nemotron" /> {RUN.generatedBy}
            </span>
            <span>
              <Timer size={13} /> {fmtDuration(t)} · started {RUN.startedAt}
            </span>
          </div>
        </div>
        <div className="run-actions">
          <button className="btn">Hold</button>
          <button className="btn" disabled title="Nothing to roll back: state is clean">
            Rollback
          </button>
          <a className="btn" href="#" onClick={(e) => e.preventDefault()}>
            Open PR !{RUN.pr} <ExternalLink size={13} />
          </a>
        </div>
      </div>

      <div className="tabs">
        {[
          ["pipeline", "Pipeline"],
          ["steps", "Steps", STEPS.length],
          ["approvals", "Approvals", approvalsOpen > 0 ? `${approvalsOpen} open` : APPROVALS.length],
          ["trace", "Trace"],
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
            <Toggle label="Show dependencies" checked={showDeps} onChange={setShowDeps} />
            <Toggle label="Fit to width" checked={fit} onChange={setFit} />
            <div className="replay">
              <button className="icon-btn" onClick={replay.toggle} aria-label={replay.playing ? "Pause" : "Replay run"}>
                {replay.playing ? <Pause size={14} /> : <Play size={14} />}
              </button>
              <input type="range" min={0} max={1} step={0.001} value={replay.p} onChange={(e) => replay.setP(Number(e.target.value))} aria-label="Run timeline" />
              <span className="mono small replay-clock">{fmtClock(RUN.startedAt, t)}</span>
            </div>
          </div>

          <div className="dag-frame">
            <Dag steps={STEPS} t={t} selectedId={selected} onSelect={(sid) => setSelected(sid === selected ? null : sid)} showDeps={showDeps} fit={fit} />
          </div>
        </>
      )}

      {tab === "steps" && (
        <div className="table steps-table">
          <div className="tr th">
            <div>Status</div>
            <div>Step</div>
            <div>Stage</div>
            <div>Type</div>
            <div>Model</div>
            <div>Duration</div>
          </div>
          {STEPS.map((s) => {
            const st = statusAt(s, t);
            return (
              <button type="button" className={cx("tr row-btn", { selected: selected === s.id })} key={s.id} onClick={() => setSelected(s.id)}>
                <div>
                  <Pill tone={st === "running" && s.type === "agent" ? "violet" : STATUS[st].tone}>{STATUS[st].label}</Pill>
                </div>
                <div>
                  <span className="row-title">{s.name}</span>
                  <span className="muted small">{s.sub}</span>
                </div>
                <div>{STAGES.find((x) => x.id === s.stage)?.name}</div>
                <div className="mono small">{s.type}</div>
                <div className="mono small">{s.model ?? "—"}</div>
                <div className="mono small">{durationAt(s, t) == null ? "—" : fmtDuration(durationAt(s, t))}</div>
              </button>
            );
          })}
        </div>
      )}

      {tab === "approvals" && <ApprovalList t={t} onOpen={(sid) => setSelected(sid)} />}

      {tab === "trace" && (
        <ol className="feed">
          {STEPS.filter((s) => TRACES[s.id]).map((s) => {
            const st = statusAt(s, t);
            if (st === "pending") return null;
            return (
              <li key={s.id} className="feed-item">
                <header>
                  <StatusIcon status={st} size={20} agent />
                  <strong>{s.name}</strong>
                  <span className="model">
                    <Sparkles size={12} /> {s.model}
                    {s.model?.includes("super") && <span className="think">/think</span>}
                  </span>
                  <span className="muted small mono">{fmtClock(RUN.startedAt, s.start)}</span>
                </header>
                <ol className="trace">
                  {TRACES[s.id].map((line, i) => (
                    <li key={i} className={cx("trace-line", `k-${line.k}`)}>
                      <span className="trace-kind">{line.k}</span>
                      <p>{line.text}</p>
                    </li>
                  ))}
                </ol>
              </li>
            );
          })}
        </ol>
      )}

      {step && <NodeDrawer step={step} t={t} onClose={() => setSelected(null)} />}
    </>
  );
}

export function ApprovalList({ t = NOW, onOpen }) {
  return (
    <div className="cards">
      {APPROVALS.map((a) => {
        const step = STEP_BY_ID[a.stepId];
        const st = statusAt(step, t);
        return (
          <article className="card" key={a.id}>
            <header className="card-head">
              <StatusIcon status={st} size={22} />
              <div className="card-title">
                <strong className="mono">{a.id}</strong>
                <span className="muted">{a.type}</span>
              </div>
              <Pill tone={STATUS[st].tone}>{STATUS[st].label}</Pill>
            </header>
            <p className="card-body">{a.justification}</p>
            <footer className="card-foot">
              <span>
                Jira <span className="mono link">{a.jira}</span>
              </span>
              <span>
                {a.team} · {a.approver}
              </span>
              <span>
                blocks{" "}
                {a.blocks.map((b) => (
                  <button key={b} className="chip" onClick={() => onOpen?.(b)}>
                    {b}
                  </button>
                ))}
              </span>
            </footer>
          </article>
        );
      })}
    </div>
  );
}
