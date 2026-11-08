import { MODE_LABEL, absTime, fmtDuration, runDuration, timeAgo } from "../util.js";
import Badge from "./Badge.jsx";
import StatusIcon from "./StatusIcon.jsx";
import { stageState } from "../util.js";

// GitLab's pipelines list: status, id, who, the stage mini-graph, duration.
export default function RunsTab({ runs, details, detail, selectedId, onSelect, requesters }) {
  if (runs.length === 0) return <div className="empty">No runs yet. Start with Build.</div>;
  return (
    <table className="table runs-table">
      <thead><tr><th>Status</th><th>Run</th><th>Requested by</th><th>Stages</th><th>Duration</th><th>When</th></tr></thead>
      <tbody>
        {runs.map((r) => {
          const d = details[r.id];
          return (
            <tr key={r.id} className={`clickable ${r.id === selectedId ? "row-active" : ""}`} onClick={() => onSelect(r.id)}>
              <td><Badge status={r.status} /></td>
              <td><span className="strong">{MODE_LABEL[r.mode]}</span> <span className="mono muted">#{r.id}</span>{r.failed_step && <div className="small muted">failed at <span className="mono">{r.failed_step}</span></div>}{r.reason && r.status === "waiting" && <div className="small muted">{r.reason}</div>}</td>
              <td>{requesters[r.id] ? <span className="who"><img className="avatar avatar-sm" src={`https://github.com/${requesters[r.id]}.png?size=32`} alt="" />{requesters[r.id]}</span> : <span className="muted">–</span>}</td>
              <td>
                <span className="mini-graph">
                  {detail.stages.map((s) => <StatusIcon key={s.name} state={d ? stageState(s, d) : "none"} size={16} title={`${s.name}: ${d ? stageState(s, d) : "unknown"}`} />)}
                </span>
              </td>
              <td>{fmtDuration(runDuration(d || { ...r, active: false }))}</td>
              <td title={absTime(r.created)}>{timeAgo(r.created)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
