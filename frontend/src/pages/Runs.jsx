import { useEffect, useState } from "react";
import { EmptyState } from "../components/Shell.jsx";
import StatusIcon, { Pill } from "../components/StatusIcon.jsx";
import { api, fmtAgo, fmtTime } from "../api.js";
import { Link } from "../router.jsx";
import { MODE_LABEL, runMeta } from "../status.js";

// Run history across every migration, newest first.
export default function Runs() {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .runs(undefined, 100)
        .then((r) => alive && (setRuns(r), setError(null)))
        .catch((e) => alive && setError(e));
    load();
    const id = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  if (error) return <EmptyState title="Backend unreachable" body={error.detail} />;
  if (!runs) return <EmptyState title="Loading…" />;

  return (
    <>
      <div className="page-head">
        <h1>Runs</h1>
        <p className="muted">Every Build, Rehearse and Deploy the runner has recorded.</p>
      </div>
      <div className="table runs-table all-runs">
        <div className="tr th">
          <div>Status</div>
          <div>Run</div>
          <div>Reason</div>
          <div>Started</div>
          <div>Updated</div>
        </div>
        {runs.map((r) => {
          const m = runMeta(r.status);
          return (
            <div className="tr" key={r.id}>
              <div>
                <Pill tone={m.tone}>
                  <StatusIcon status={m.icon} size={14} />
                  {m.label}
                </Pill>
              </div>
              <div className="cell-title">
                <Link to={`/migrations/${encodeURIComponent(r.migration)}?run=${r.id}`} className="row-title">
                  {MODE_LABEL[r.mode]} · {r.migration}
                </Link>
                <span className="mono small muted">{r.id}</span>
              </div>
              <div className="small reason" title={r.reason ?? ""}>
                  {r.reason ?? (r.failed_step ? `failed at ${r.failed_step}` : "—")}
                </div>
              <div className="small">
                {fmtTime(r.created)} <span className="muted">· {fmtAgo(r.created)}</span>
              </div>
              <div className="small">{fmtTime(r.updated)}</div>
            </div>
          );
        })}
        {runs.length === 0 && <div className="tr empty-row">No runs yet.</div>}
      </div>
    </>
  );
}
