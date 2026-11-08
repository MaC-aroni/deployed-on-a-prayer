import { useEffect, useState } from "react";
import { ExternalLink, Sparkles, X } from "lucide-react";
import StatusIcon, { Pill } from "./StatusIcon.jsx";
import { LOGS, SPECS, STAGES, STATUS, TRACES, durationAt, statusAt } from "../data/mock.js";
import { cx, fmtDuration } from "../lib.js";

function Typewriter({ text, active }) {
  const [n, setN] = useState(active ? 0 : text.length);
  useEffect(() => {
    if (!active) return setN(text.length);
    setN(0);
    const id = setInterval(() => setN((v) => (v >= text.length ? (clearInterval(id), v) : v + 2)), 22);
    return () => clearInterval(id);
  }, [text, active]);
  return (
    <>
      {text.slice(0, n)}
      {active && n < text.length && <span className="caret" />}
    </>
  );
}

function fallbackSpec(step) {
  const lines = [`- id: ${step.id}`, `  type: ${step.type}`];
  if (step.needs.length) lines.push(`  needs: [${step.needs.join(", ")}]`);
  if (step.gate) lines.push(`  gate: ${step.gate}`);
  if (step.model) lines.push(`  model: ${step.model}`);
  if (step.jira) lines.push(`  jira: ${step.jira}`);
  return lines.join("\n");
}

// Inspector panel for a selected DAG node. Docks under the DAG so the
// Deploy and Recover columns stay visible while the reasoning streams.
export default function NodeDrawer({ step, t, onClose }) {
  const isAgent = step.type === "agent";
  const [tab, setTab] = useState(isAgent ? "reasoning" : "logs");
  useEffect(() => setTab(isAgent ? "reasoning" : "logs"), [step.id, isAgent]);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const status = statusAt(step, t);
  const stage = STAGES.find((s) => s.id === step.stage);
  const trace = TRACES[step.id];
  const logs = LOGS[step.id];
  const spec = SPECS[step.id] ?? fallbackSpec(step);
  const dur = durationAt(step, t);

  const tabs = [
    isAgent && { id: "reasoning", label: "Reasoning" },
    { id: "logs", label: "Logs" },
    { id: "spec", label: "Spec" },
  ].filter(Boolean);

  return (
    <section className="inspector" aria-label={step.name}>
      <header className="inspector-head">
        <StatusIcon status={status} size={28} agent={isAgent} />
        <div className="inspector-title">
          <h2>{step.name}</h2>
          <span className="muted small">{step.sub}</span>
        </div>
        <div className="inspector-meta">
          <Pill tone={status === "running" && isAgent ? "violet" : STATUS[status].tone}>{STATUS[status].label}</Pill>
          <span className="meta-chip">
            <span className="muted">stage</span> {stage?.name}
          </span>
          <span className="meta-chip">
            <span className="muted">type</span> <span className="mono">{step.type}</span>
          </span>
          {step.model && (
            <span className="meta-chip model">
              <Sparkles size={12} /> {step.model}
              {step.model.includes("super") && <span className="think">/think</span>}
            </span>
          )}
          {step.jira && (
            <a className="meta-chip link mono" href="#" onClick={(e) => e.preventDefault()}>
              {step.jira} <ExternalLink size={11} />
            </a>
          )}
          <span className="meta-chip">
            <span className="muted">duration</span> <span className="mono">{dur == null ? "—" : fmtDuration(dur)}</span>
          </span>
          {step.needs.length > 0 && (
            <span className="meta-chip">
              <span className="muted">needs</span> <span className="mono">{step.needs.join(", ")}</span>
            </span>
          )}
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={16} />
        </button>
      </header>

      <div className="inspector-split">
        <nav className="tabs tabs-vertical">
          {tabs.map((tb) => (
            <button key={tb.id} className={cx("tab", { active: tab === tb.id })} onClick={() => setTab(tb.id)}>
              {tb.label}
            </button>
          ))}
        </nav>

        <div className="inspector-body">
          {tab === "reasoning" && status === "pending" && <p className="muted">Step has not started. The trace appears once {step.model} picks it up.</p>}
          {tab === "reasoning" && status !== "pending" && (
            <ol className="trace">
              {(trace ?? [{ k: "observation", text: "No trace recorded for this step in the mock." }]).map((line, i) => (
                <li key={i} className={cx("trace-line", `k-${line.k}`)}>
                  <span className="trace-kind">{line.k}</span>
                  <p>{line.live && status === "running" ? <Typewriter text={line.text} active /> : line.text}</p>
                </li>
              ))}
              {status === "running" && isAgent && (
                <li className="trace-line k-pending">
                  <span className="trace-kind">…</span>
                  <p className="muted">streaming from {step.model}</p>
                </li>
              )}
            </ol>
          )}
          {tab === "logs" && (
            <pre className="log">
              {(logs ?? [status === "pending" ? "step has not started" : `${step.id}: ${STATUS[status].label.toLowerCase()} in ${fmtDuration(dur)}`]).join("\n")}
            </pre>
          )}
          {tab === "spec" && <pre className="log yaml">{spec}</pre>}
        </div>
      </div>
    </section>
  );
}
