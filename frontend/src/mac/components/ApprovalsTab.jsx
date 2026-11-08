import { useState } from "react";
import { absTime, timeAgo } from "../util.js";
import Badge from "./Badge.jsx";
import StatusIcon from "./StatusIcon.jsx";

function Approval({ a, report, detail, children }) {
  const [open, setOpen] = useState(false);
  const r = report?.[a.id];
  const status = r?.ticket || r?.url || a.ticket ? (r?.status || "pending") : (r?.status === "pending" || !r ? "not_requested" : r.status);
  const unblocks = detail.stages.flatMap((s) => s.steps).filter((s) => s.requires_approval.includes(a.id)).map((s) => s.id);
  return (
    <li className={`appr appr-${status}`}>
      <div className="appr-node"><StatusIcon state={status} size={20} /></div>
      <div className="appr-body">
        <div className="appr-title">
          <Badge status={status} kind="approval" />
          <span className="mono strong">{a.id}</span>
          <span className="muted">· {a.type.replaceAll("_", " ")} · approver <b>{a.approver}</b></span>
          {(r?.url || a.ticket) && <a className="appr-ticket" href={r?.url || a.ticket.url} target="_blank" rel="noreferrer">{r?.ticket || a.ticket.key} ↗</a>}
          {a.design_doc && detail.design_page && <a className="appr-ticket" href={detail.design_page.url} target="_blank" rel="noreferrer">design page ↗</a>}
        </div>
        <div className="appr-summary">{a.summary}</div>
        {r?.detail && r.detail !== r.ticket && <div className="appr-detail">{r.detail}</div>}
        {status === "rejected" && <div className="alert alert-danger small">A rejected approval fails the Deploy and undoes everything it did.</div>}
        <div className="muted small">Unblocks in Deploy: {unblocks.length ? unblocks.map((s) => <span key={s} className="mono chip">{s}</span>) : "nothing directly"}{a.design_doc && " · needs the design page first"}</div>
        <button className="link small" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} justification</button>
        {open && <blockquote className="appr-why">{a.justification}</blockquote>}
        {children}
      </div>
    </li>
  );
}

export default function ApprovalsTab({ detail, build, run, onCheck, locked }) {
  const report = build?.report?.approvals;
  const roots = detail.approvals.filter((a) => !a.after?.length);
  const childrenOf = (id) => detail.approvals.filter((a) => a.after?.includes(id));
  const waiting = run?.status === "waiting" && /approv/i.test(run.reason || "");
  const render = (a) => (
    <Approval key={a.id} a={a} report={report} detail={detail}>
      {childrenOf(a.id).length > 0 && (
        <ul className="appr-chain">
          <div className="appr-after muted small">then, once approved →</div>
          {childrenOf(a.id).map(render)}
        </ul>
      )}
    </Approval>
  );
  return (
    <div className="approvals">
      <div className="approvals-bar">
        <span className="muted small">
          {build ? <>Statuses as of Build <span className="mono">#{build.id}</span>, {timeAgo(build.created)} ({absTime(build.created)}). There's no Jira push: check again to refresh.</> : "No Build yet, so no tickets have been raised."}
        </span>
        <span className="spacer" />
        <button className="btn" disabled={!waiting || locked} onClick={onCheck} title={waiting ? "Ask Jira again and continue the waiting run" : "Enabled while a Deploy is waiting on an approval"}>Check approvals</button>
      </div>
      <ul className="appr-list">{roots.map(render)}</ul>
      <p className="muted small">MaC raises one ticket per approval per version of <span className="mono">migration.yaml</span>, in code from the spec. Editing the plan raises fresh tickets. Only Deploy waits for approvals; Rehearse runs without them because it only touches the rehearsal environment.</p>
    </div>
  );
}
