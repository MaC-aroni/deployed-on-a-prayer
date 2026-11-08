import { useEffect, useState } from "react";
import { Cloud, Search, Users } from "lucide-react";
import { EmptyState } from "../components/Shell.jsx";
import StatusIcon, { Pill } from "../components/StatusIcon.jsx";
import { api, fmtAgo } from "../api.js";
import { Link } from "../router.jsx";
import { MODE_LABEL, runMeta } from "../status.js";
import { cx } from "../lib.js";

const ACTIVE = new Set(["running", "waiting", "rolling_back"]);

// The run that best describes where a migration is: an active one, else the newest.
function headline(latest) {
  const runs = ["build", "rehearse", "deploy"].map((mode) => latest?.[mode] && { mode, ...latest[mode] }).filter(Boolean);
  if (!runs.length) return null;
  return runs.find((r) => ACTIVE.has(r.status)) ?? runs.sort((a, b) => b.updated - a.updated)[0];
}

function MiniRun({ mode, run }) {
  if (!run) return <span className="mini muted">{MODE_LABEL[mode]} —</span>;
  const m = runMeta(run.status);
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
      api
        .migrations()
        .then((r) => alive && (setRows(r), setError(null)))
        .catch((e) => alive && setError(e));
    load();
    const id = setInterval(load, 5000);
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
  if (!rows) return <EmptyState title="Loading…" />;

  const shown = rows.filter((m) => !q || `${m.name} ${m.service ?? ""} ${m.owner_team ?? ""}`.toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <div className="page-head">
        <h1>Migrations</h1>
        <p className="muted">Every migration.yaml the runner knows about. Build checks it, Rehearse proves it, Deploy ships it.</p>
      </div>

      <div className="toolbar">
        <label className="filter">
          <Search size={15} />
          <input placeholder="Filter migrations" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
      </div>

      <div className="table migrations-table">
        <div className="tr th">
          <div>Status</div>
          <div>Migration</div>
          <div>Runs</div>
          <div>Stages</div>
          <div />
        </div>
        {shown.map((m) => {
          const head = headline(m.latest);
          const hm = head ? runMeta(head.status) : runMeta("none");
          return (
            <div className="tr" key={m.name}>
              <div className="cell-status">
                {m.valid ? (
                  <Pill tone={hm.tone}>
                    <StatusIcon status={hm.icon} size={14} />
                    {head ? `${MODE_LABEL[head.mode]} ${hm.label.toLowerCase()}` : hm.label}
                  </Pill>
                ) : (
                  <Pill tone="red">
                    <StatusIcon status="failed" size={14} /> Invalid spec
                  </Pill>
                )}
                {head && <span className="muted small">{fmtAgo(head.updated)}</span>}
              </div>
              <div className="cell-title">
                <Link to={`/migrations/${encodeURIComponent(m.name)}`} className="row-title">
                  {m.service ?? m.name}
                </Link>
                <span className="row-meta">
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
                {m.problems?.length > 0 && <span className="small tone-red problems">{m.problems.join("; ")}</span>}
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
                <Link to={`/migrations/${encodeURIComponent(m.name)}`} className="btn btn-ghost">
                  Open
                </Link>
              </div>
            </div>
          );
        })}
        {shown.length === 0 && <div className="tr empty-row">No migrations match.</div>}
      </div>
    </>
  );
}
