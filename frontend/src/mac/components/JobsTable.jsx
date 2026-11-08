import { STEP_TYPE, fmtDuration, githubUrl, repoName, shortSha } from "../util.js";
import Badge from "./Badge.jsx";

export default function JobsTable({ detail, run, timings, onSelect, onPlay, locked }) {
  const steps = detail.stages.flatMap((s) => s.steps);
  return (
    <table className="table">
      <thead>
        <tr><th>Status</th><th>Step</th><th>Stage</th><th>Type</th><th>Repository</th><th>Duration</th><th aria-label="Actions" /></tr>
      </thead>
      <tbody>
        {steps.map((step) => {
          const state = run?.steps?.[step.id] || "none";
          const sha = shortSha(step.repo, run?.shas);
          return (
            <tr key={step.id} className="clickable" onClick={() => onSelect(step.id)}>
              <td><Badge status={state} kind="step" /></td>
              <td><span className="mono strong">{step.id}</span>{step.codegen === "llm" && <span className="chip chip-ai">AI</span>}{step.when === "manual" && <span className="chip">manual</span>}</td>
              <td>{step.stage}</td>
              <td>{STEP_TYPE[step.type]}</td>
              <td><a href={githubUrl(step.repo, run?.shas, step.path || step.entrypoint)} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="mono">{repoName(step.repo)}{sha ? ` @ ${sha}` : ""}</a><div className="muted small mono">{step.path ? `${step.path}/` : step.entrypoint}</div></td>
              <td>{timings?.[step.id]?.duration != null ? fmtDuration(timings[step.id].duration) : <span className="muted">–</span>}</td>
              <td className="row-actions">{state === "waiting" && !locked && <button className="btn btn-sm" onClick={(e) => { e.stopPropagation(); onPlay(step.id); }}>▶ Run</button>}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
