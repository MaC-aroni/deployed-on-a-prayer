import { absTime } from "../util.js";

const MODE_NAME = { explain: "Explain", report: "Report", autofix: "Auto-fix" };

// The AI's take after a failure: one card per `diagnosis` event, newest first.
export default function DiagnosisCard({ run, events }) {
  const items = events.filter((e) => e.kind === "diagnosis").reverse();
  if (items.length === 0) return null;
  return (
    <section className="diagnosis">
      <div className="diagnosis-head">
        <span className="chip chip-ai">AI</span>
        <strong>Diagnosis</strong>
        <span className="muted small">mode: {MODE_NAME[run.diagnostics_mode] || run.diagnostics_mode}{run.failed_step && <> · failed step <span className="mono">{run.failed_step}</span></>}</span>
      </div>
      {items.map((e) => (
        <article key={e.seq} className="diagnosis-item">
          <div className="muted small">{absTime(e.ts)}{e.step && <> · <span className="mono">{e.step}</span></>}</div>
          {e.message.split(/\n{2,}/).map((p, i) => <p key={i}>{p}</p>)}
        </article>
      ))}
      {run.diagnostics_mode === "report" && <div className="muted small">The downloadable report (.md) arrives once the Report mode is connected.</div>}
      {run.diagnostics_mode === "autofix" && <div className="muted small">Auto-fix works on a branch <span className="mono">mac/autofix/{run.id}</span> and re-runs Build and Rehearse up to three times, then opens a PR. A rehearsal on a branch can never be deployed.</div>}
    </section>
  );
}
