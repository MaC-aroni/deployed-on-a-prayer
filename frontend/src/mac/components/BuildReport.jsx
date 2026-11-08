import { STEP_TYPE, absTime, githubUrl, planSummary, repoName, requestedBy, shortSha, timeAgo } from "../util.js";
import Badge from "./Badge.jsx";
import StatusIcon from "./StatusIcon.jsx";

const CHECKS = [["ci_green", "CI green"], ["protected_branch", "Protected branch"], ["reviewed", "Reviewed PR"]];

export default function BuildReport({ build, events, detail, onRehearse, canRehearse }) {
  if (!build) return <div className="empty">No Build yet. Build checks the repos, writes the design page, raises the approval tickets that are due and plans every Terraform step, without changing anything in AWS.</div>;
  const report = build.report || {};
  const guardrails = report.guardrails || {};
  const steps = detail.stages.flatMap((s) => s.steps);
  const who = requestedBy(events);
  return (
    <div className="report">
      <div className="report-head">
        <StatusIcon state={build.status} size={22} />
        <div>
          <div className="strong">Build <span className="mono">#{build.id}</span> · {absTime(build.created)}</div>
          <div className="muted small">{timeAgo(build.created)}{who ? ` · requested by @${who}` : ""}{build.spec_digest ? ` · spec ${build.spec_digest.slice(0, 7)}` : ""}{build.reason ? ` · ${build.reason}` : ""}</div>
        </div>
        <span className="spacer" />
        {onRehearse && <button className="btn btn-confirm" disabled={!canRehearse} onClick={onRehearse} title={canRehearse ? "" : "Needs a passing Build and no run in progress"}>Rehearse these commits</button>}
      </div>

      <h3>Guardrails <span className="muted small">inherited from each repo, checked on GitHub</span></h3>
      {Object.keys(guardrails).length === 0 ? <div className="empty">No guardrail results: the Build stopped before checking the repos.</div> : (
        <table className="table">
          <thead><tr><th>Repository</th><th>Locked commit</th>{CHECKS.map(([k, l]) => <th key={k}>{l}</th>)}</tr></thead>
          <tbody>
            {Object.entries(guardrails).map(([repo, checks]) => {
              const by = Object.fromEntries(checks.map((c) => [c.name, c]));
              const sha = shortSha(repo, build.shas);
              return (
                <tr key={repo} className={checks.every((c) => c.passed) ? "" : "row-danger"}>
                  <td><a href={githubUrl(repo, build.shas)} target="_blank" rel="noreferrer" className="mono">{repoName(repo)}</a></td>
                  <td className="mono">{sha || "–"}</td>
                  {CHECKS.map(([k]) => <td key={k}>{by[k] ? <span title={by[k].detail}><StatusIcon state={by[k].passed ? "succeeded" : "failed"} size={14} /> <span className="small">{by[k].detail.replace(/^ok: /, "")}</span></span> : <span className="muted">–</span>}</td>)}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <h3>Design page <span className="muted small">written by the LLM for Tech Risk, published to Confluence</span></h3>
      <div className="report-line">
        {report.design_page?.url || detail.design_page?.url ? (
          <><StatusIcon state="succeeded" size={14} /> <a href={report.design_page?.url || detail.design_page.url} target="_blank" rel="noreferrer">Open in Confluence</a>{detail.design_page && !detail.design_page.current && <span className="muted"> · out of date: the spec changed, the next Build rewrites it</span>}</>
        ) : (
          <><StatusIcon state="pending" size={14} /> <span>{report.design_page?.status || "not written"}</span><span className="muted"> · the Build still passed; the Tech Risk ticket waits for the page and the next Build tries again</span></>
        )}
      </div>

      <h3>Approvals <span className="muted small">as of this Build</span></h3>
      <table className="table">
        <thead><tr><th>Status</th><th>Approval</th><th>Approver</th><th>Ticket</th><th>Detail</th></tr></thead>
        <tbody>
          {detail.approvals.map((a) => {
            const r = report.approvals?.[a.id];
            const status = r?.ticket || r?.url || a.ticket ? (r?.status || "pending") : (r?.status === "pending" || !r ? "not_requested" : r.status);
            return (
              <tr key={a.id}>
                <td><Badge status={status} kind="approval" /></td>
                <td className="mono strong">{a.id}</td>
                <td>{a.approver}</td>
                <td>{(r?.url || a.ticket) ? <a href={r?.url || a.ticket.url} target="_blank" rel="noreferrer">{r?.ticket || a.ticket.key}</a> : <span className="muted">not raised yet</span>}</td>
                <td className="small">{r?.detail && r.detail !== r.ticket ? r.detail : a.summary}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h3>What will run <span className="muted small">in order; Rehearse and Deploy use exactly these commits</span></h3>
      <table className="table">
        <thead><tr><th>Step</th><th>Type</th><th>In this Build</th><th>Undo</th></tr></thead>
        <tbody>
          {steps.map((step) => {
            const state = build.steps?.[step.id];
            const plan = planSummary(events, step.id);
            return (
              <tr key={step.id}>
                <td><span className="mono strong">{step.id}</span>{step.when === "manual" && <span className="chip">manual</span>}{step.codegen === "llm" && <span className="chip chip-ai">AI</span>}</td>
                <td>{STEP_TYPE[step.type]}</td>
                <td>
                  {plan ? <span className="plan-sum"><b className="tr-add">+{plan.add}</b> <b className="tr-chg">~{plan.change}</b> <b className="tr-del">−{plan.destroy}</b> <span className="muted small">planned</span></span>
                    : state ? <Badge status={state} kind="step" label={state === "succeeded" ? "ran, passed" : undefined} />
                    : <span className="muted small">{step.type === "check" ? "runs after a change; not run in Build" : "not previewed"}</span>}
                </td>
                <td className="small">{step.rollback ? <span className="mono">{step.rollback}</span> : <span className="muted">none</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {report.issues?.length > 0 && (<><h3>Issues</h3><ul className="issues">{report.issues.map((i) => <li key={i}>{i}</li>)}</ul></>)}
    </div>
  );
}
