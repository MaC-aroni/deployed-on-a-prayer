import { maskAccount } from "../util.js";
import StatusIcon from "./StatusIcon.jsx";

export default function Sidebar({ migrations, name, onSelect, detail, open }) {
  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="side-section">
        <div className="side-title">Migrations</div>
        {migrations.map((m) => {
          const latest = m.latest?.deploy || m.latest?.rehearse || m.latest?.build;
          return (
            <button key={m.name} className={`side-item ${m.name === name ? "active" : ""}`} onClick={() => onSelect(m.name)}>
              <StatusIcon state={m.valid ? (latest?.status === "succeeded" ? "succeeded" : latest?.status === "failed" || latest?.status === "rollback_failed" ? "failed" : latest ? latest.status : "none") : "failed"} />
              <span className="side-text">
                <span className="side-name">{m.service || m.name}</span>
                <span className="side-sub">{m.valid ? m.name : "invalid migration.yaml"}</span>
              </span>
            </button>
          );
        })}
        {migrations.length === 0 && <div className="side-empty">No migration.yaml found.</div>}
      </div>
      <div className="side-section side-soon">
        <div className="side-title">Agents</div>
        {["Knowledge graph", "Planner", "Guide writer", "Code writer"].map((a) => (
          <div key={a} className="side-item disabled" title="CLI only for now; API endpoints are next"><span className="side-text"><span className="side-name">{a}</span><span className="side-sub">CLI · coming to the console</span></span></div>
        ))}
      </div>
      {detail && (
        <div className="side-foot">
          <div className="side-title">Target</div>
          <dl className="kv">
            <dt>Provider</dt><dd>{detail.target.provider.toUpperCase()}</dd>
            <dt>Region</dt><dd>{detail.target.region}</dd>
            <dt>Account</dt><dd title={detail.target.account}>{maskAccount(detail.target.account)}</dd>
            <dt>Owner</dt><dd>{detail.owner_team}</dd>
          </dl>
        </div>
      )}
    </aside>
  );
}
