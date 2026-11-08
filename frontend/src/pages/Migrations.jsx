import { useEffect, useState } from "react";
import { Cloud, Search, Sparkles, Users, Wand2 } from "lucide-react";
import { EmptyState, markPipelinesSeen } from "../components/Shell.jsx";
import Gauge from "../components/Gauge.jsx";
import StatusIcon, { Pill } from "../components/StatusIcon.jsx";
import { api, fmtAgo } from "../mac/api.js";
import { SkeletonPage } from "../components/Skeleton.jsx";
import { Link, navigate } from "../router.jsx";
import { MODE_LABEL, runMeta } from "../status.js";
import { cx } from "../lib.js";

// Pipelines: the reviewed specs in examples/ and the plans the Planner generated, one table.

const ACTIVE = new Set(["running", "waiting", "rolling_back"]);

// The run that best describes where a migration is: an active one, else the newest.
function headline(latest) {
  const runs = ["build", "rehearse", "deploy"].map((mode) => latest?.[mode] && { mode, ...latest[mode] }).filter(Boolean);
  if (!runs.length) return null;
  return runs.find((r) => ACTIVE.has(r.status)) ?? runs.sort((a, b) => b.updated - a.updated)[0];
}

function MiniRun({ mode, run }) {
  if (!run) return <span className="mini muted">{MODE_LABEL[mode]} —</span>;
  const m = runMeta(run.status, run.mode);
  return (
    <span className={cx("mini", `tone-${m.tone}`)} title={run.reason ?? ""}>
      <StatusIcon status={m.icon} size={14} />
      <span>
        {MODE_LABEL[mode]} <span className="muted">· {fmtAgo(run.updated)}</span>
      </span>
    </span>
  );
}

export default function Migrations() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    let alive = true;
    const load = () =>
      Promise.all([api.migrations(), api.plans().catch(() => [])])
        .then(([migs, plans]) => {
          if (!alive) return;
          setRows([
            ...migs.map((m) => ({ ...m, key: `m:${m.name}`, href: `/migrations/${encodeURIComponent(m.name)}`, source: "reviewed" })),
            ...plans.map((p) => ({ ...p, key: `p:${p.run_id}`, href: `/plans/${p.run_id}`, source: "generated", path: `plan ${p.run_id}` })),
          ]);
          setError(null);
        })
        .catch((e) => alive && setError(e));
    load();
    const id = setInterval(load, 10000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (error) {
    return (
      <EmptyState title="Backend unreachable" body={error.detail}>
        <p className="muted small">The runner API is at /api/mac. Locally, start everything with `mise run dev-local`.</p>
      </EmptyState>
    );
  }
  // Seen: the badge in the sidebar glows only for pipelines this viewer hasn't listed yet.
  useEffect(() => {
    if (rows) markPipelinesSeen(rows.map((r) => r.key));
  }, [rows]);

  if (!rows) return <SkeletonPage rows={4} cols={5} />;

  const shown = rows.filter((m) => !q || `${m.name} ${m.service ?? ""} ${m.owner_team ?? ""} ${m.source}`.toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <div className="page-head">
        <h1>Pipelines</h1>
        <p className="muted">Every migration renders a pipeline here: reviewed migration.yaml files and the ones the agent wrote. Build checks one, Rehearse proves it, Deploy ships it. Breakpoints pause it until you continue.</p>
      </div>

      <div className="metrics">
        <div className="metric">
          <span className="label">Pipelines</span>
          <span className="metric-value">{rows.length}</span>
          <span className="metric-sub">{rows.filter((r) => r.source === "reviewed").length} reviewed · {rows.filter((r) => r.source === "generated").length} planned by Nemotron</span>
        </div>
        <div className="metric">
          <span className="label">Active runs</span>
          <span className="metric-value">{rows.filter((r) => headline(r.latest) && ACTIVE.has(headline(r.latest).status)).length}</span>
          <span className="metric-sub">Build, Rehearse or Deploy in progress</span>
        </div>
        <Link to="/services" className="metric metric-link" title="Open Services">
          <span className="label">Deployed</span>
          <span className="metric-value">{rows.filter((r) => r.latest?.deploy?.status === "succeeded").length}</span>
          <span className="metric-sub">pipelines with a passing Deploy · see Services</span>
        </Link>
      </div>

      <div className="toolbar">
        <label className="filter">
          <Search size={15} />
          <input placeholder="Filter pipelines" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <Link to="/migrate" className="btn btn-primary">
          <Wand2 size={14} /> Migrate a service
        </Link>
      </div>

      <div className="table migrations-table">
        <div className="tr th">
          <div>Status</div>
          <div>Pipeline</div>
          <div>Runs</div>
          <div>Stages</div>
          <div />
        </div>
        {shown.map((m) => {
          const head = headline(m.latest);
          const hm = head ? runMeta(head.status, head.mode) : runMeta("none");
          return (
            <button type="button" className="tr row-btn" key={m.key} onClick={() => navigate(m.href)}>
              <div className="cell-status">
                <Gauge size={44} active={Boolean(head && ACTIVE.has(head.status))} stages={(m.stages ?? []).map((name) => ({ name, status: head ? (head.status === "succeeded" ? "succeeded" : head.failed_step ? "failed" : head.status) : "pending" }))} title={head ? `${MODE_LABEL[head.mode]} ${hm.label.toLowerCase()}` : "no runs yet"} />
                {m.valid === false ? (
                  <Pill tone="red">
                    <StatusIcon status="failed" size={14} /> Invalid spec
                  </Pill>
                ) : (
                  <Pill tone={hm.tone}>
                    <StatusIcon status={hm.icon} size={14} />
                    {head ? `${MODE_LABEL[head.mode]} ${hm.label.toLowerCase()}` : hm.label}
                  </Pill>
                )}
                {head && <span className="muted small">{fmtAgo(head.updated)}</span>}
              </div>
              <div className="cell-title">
                <Link to={m.href} className="row-title" onClick={(e) => e.stopPropagation()}>
                  {m.service ?? m.name}
                </Link>
                <span className="row-meta">
                  {m.source === "generated" ? (
                    <Link to={`/migrate/${m.run_id}`} className="pill tone-violet tag pill-link" title="Open the planning run" onClick={(e) => e.stopPropagation()}>
                      <Sparkles size={11} /> planned by Nemotron
                    </Link>
                  ) : (
                    <Pill tone="grey" className="tag">
                      reviewed
                    </Pill>
                  )}
                  <span className="mono">{m.name}</span>
                  {m.owner_team && (
                    <span>
                      <Users size={12} /> {m.owner_team}
                    </span>
                  )}
                  <span>
                    <Cloud size={12} /> {m.path}
                  </span>
                </span>
                {m.problems?.length > 0 && <span className="small problems">{m.problems.join("; ")}</span>}
              </div>
              <div className="cell-runs">
                {["build", "rehearse", "deploy"].map((mode) => (
                  <MiniRun key={mode} mode={mode} run={m.latest?.[mode]} />
                ))}
              </div>
              <div className="cell-stages">
                {(m.stages ?? []).map((s) => (
                  <span key={s} className="stage-chip">
                    {s}
                  </span>
                ))}
              </div>
              <div className="cell-actions">
                <span className="btn btn-ghost row-action">Open</span>
              </div>
            </button>
          );
        })}
        {shown.length === 0 && rows.length > 0 && <div className="tr empty-row">No pipelines match.</div>}
        {rows.length === 0 && (
          <div className="tr empty-row empty-pipelines">
            <strong>No pipelines yet.</strong>
            <span className="muted">Pipelines are generated by migrations: pick a service under Migration, and the agent detects or writes its migration.yaml and starts Build.</span>
            <Link to="/migrate" className="btn btn-primary">
              <Wand2 size={14} /> Start a migration
            </Link>
          </div>
        )}
      </div>
    </>
  );
}
