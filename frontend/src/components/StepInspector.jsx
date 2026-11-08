import { useEffect, useRef, useState } from "react";
import { Bot, Hand, Play, X } from "lucide-react";
import StatusIcon, { Pill } from "./StatusIcon.jsx";
import { fmtTime, repoKey, shortRepo } from "../mac/api.js";
import { STATUS } from "../status.js";
import { cx } from "../lib.js";

function specText(step) {
  const lines = [`- id: ${step.id}`, `  stage: ${step.stage}`, `  type: ${step.type}`];
  if (step.when && step.when !== "auto") lines.push(`  when: ${step.when}`);
  if (step.codegen && step.codegen !== "engineer") lines.push(`  codegen: ${step.codegen}`);
  if (step.needs?.length) lines.push(`  needs: [${step.needs.join(", ")}]`);
  if (step.requires_approval?.length) lines.push(`  requires_approval: [${step.requires_approval.join(", ")}]`);
  lines.push("  run:", `    repo: ${step.repo}`);
  if (step.entrypoint) lines.push(`    entrypoint: ${step.entrypoint}`);
  if (step.path) lines.push(`    path: ${step.path}`);
  if (step.verify) lines.push("  verify:", `    entrypoint: ${step.verify}`);
  if (step.rollback) lines.push(`  rollback: ${step.rollback.startsWith("terraform") ? step.rollback : `{ entrypoint: ${step.rollback} }`}`);
  else lines.push("  rollback: none");
  return lines.join("\n");
}

// Detail panel for a step of the live pipeline, docked under the DAG.
export default function StepInspector({ step, state, run, events, onPlay, onClose, busy }) {
  const [tab, setTab] = useState("logs");
  const logRef = useRef(null);
  const mine = events.filter((e) => e.step === step.id);
  const sha = run?.shas?.[repoKey(step.repo)];

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [mine.length, tab]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <section className="inspector" aria-label={step.id}>
      <header className="inspector-head">
        <StatusIcon status={state} size={28} />
        <div className="inspector-title">
          <h2 className="mono">{step.id}</h2>
          <span className="muted small">
            {step.type} · {shortRepo(step.repo)}
          </span>
        </div>
        <div className="inspector-meta">
          <Pill tone={STATUS[state]?.tone ?? "grey"}>{STATUS[state]?.label ?? state}</Pill>
          {step.when === "manual" && (
            <span className="meta-chip">
              <Hand size={12} /> manual
            </span>
          )}
          {step.codegen === "llm" && (
            <span className="meta-chip ai-badge">
              <Bot size={12} /> AI writes this step
            </span>
          )}
          <span className="meta-chip">
            <span className="muted">repo</span>{" "}
            <span className="mono">
              {shortRepo(step.repo)}
              {sha ? `@${sha.slice(0, 7)}` : `@${step.repo.split("@")[1] ?? "main"}`}
            </span>
          </span>
          {step.entrypoint && (
            <span className="meta-chip">
              <span className="muted">run</span> <span className="mono">{step.entrypoint}</span>
            </span>
          )}
          {step.path && (
            <span className="meta-chip">
              <span className="muted">path</span> <span className="mono">{step.path}</span>
            </span>
          )}
          {step.verify && (
            <span className="meta-chip">
              <span className="muted">verify</span> <span className="mono">{step.verify}</span>
            </span>
          )}
          <span className="meta-chip">
            <span className="muted">undo</span> <span className="mono">{step.rollback ?? "none"}</span>
          </span>
          {step.requires_approval?.length > 0 && (
            <span className="meta-chip">
              <span className="muted">needs approval</span> <span className="mono">{step.requires_approval.join(", ")}</span>
            </span>
          )}
        </div>
        {state === "waiting" && (
          <button className="btn btn-primary" onClick={() => onPlay(step.id)} disabled={busy}>
            <Play size={14} /> Play
          </button>
        )}
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={16} />
        </button>
      </header>

      <div className="inspector-split">
        <nav className="tabs tabs-vertical">
          {[
            ["logs", `Logs${mine.length ? ` (${mine.length})` : ""}`],
            ["spec", "Spec"],
          ].map(([id, label]) => (
            <button key={id} className={cx("tab", { active: tab === id })} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </nav>
        <div className="inspector-body">
          {tab === "logs" && (
            <pre className="log" ref={logRef}>
              {mine.length === 0
                ? run
                  ? `no output from ${step.id} in this ${run.mode} yet`
                  : "no run selected"
                : mine.map((e) => `${fmtTime(e.ts)}  ${e.kind === "log" ? "" : `[${e.kind}] `}${e.message}`).join("\n")}
            </pre>
          )}
          {tab === "spec" && <pre className="log yaml">{specText(step)}</pre>}
        </div>
      </div>
    </section>
  );
}
