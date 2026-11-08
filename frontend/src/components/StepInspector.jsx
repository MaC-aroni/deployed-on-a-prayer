import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Copy, Download, ExternalLink, Play, X } from "lucide-react";
import StatusIcon, { Pill } from "./StatusIcon.jsx";
import { fmtTime, githubUrl, shortRepo, shortSha } from "../mac/api.js";
import { STATUS } from "../status.js";
import { cx } from "../lib.js";

// Detail panel for a step of the live pipeline, docked under the graph: the step's output on
// the left, and on the right everything the step points at (repo at the locked commit, files,
// undo, approvals it waits for, sources), with links into GitHub and Jira.

const STEP_TYPE = { check: "Check", script: "Script", iac: "Terraform", db_migration: "Data migration" };

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
  if (step.sources?.length) lines.push(`  sources: [${step.sources.join(", ")}]`);
  return lines.join("\n");
}

// Colour Terraform plan output the way a diff reads.
function lineClass(e) {
  if (e.kind !== "log") return `ln-${e.kind}`;
  const t = e.message.trimStart();
  if (t.startsWith("+")) return "ln-add";
  if (t.startsWith("-") && !t.startsWith("--")) return "ln-del";
  if (t.startsWith("~")) return "ln-chg";
  if (t.startsWith("$ ")) return "ln-cmd";
  if (/\b(error|failed|traceback)\b/i.test(t)) return "ln-err";
  return "";
}

function Row({ label, children }) {
  if (children == null || children === "" || children === false) return null;
  return (
    <div className="job-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export default function StepInspector({ step, state, run, events, approvals = [], report, onPlay, onClose, busy }) {
  const [tab, setTab] = useState("logs");
  const [query, setQuery] = useState("");
  const logRef = useRef(null);
  const mine = useMemo(
    () => events.filter((e) => e.step === step.id && e.kind !== "step" && (!query || e.message.toLowerCase().includes(query.toLowerCase()))),
    [events, step.id, query],
  );
  const shas = run?.shas;
  const sha = shortSha(step.repo, shas);
  const env = run?.mode === "deploy" ? "production" : run?.mode === "rehearse" ? "rehearsal" : null;
  const waits = (step.requires_approval ?? []).map((id) => ({ id, a: approvals.find((x) => x.id === id), r: report?.approvals?.[id] }));

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [mine.length, tab]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const text = () => mine.map((e) => `${fmtTime(e.ts)}  ${e.message}`).join("\n");
  const download = () => {
    const blob = new Blob([text()], { type: "text/plain" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `${run?.mode ?? "step"}-${run?.id ?? ""}-${step.id}.log` });
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <section className="inspector" aria-label={step.id}>
      <div className="inspector-grid">
        <div className="inspector-main">
          <header className="inspector-bar">
            <nav className="tabs tabs-small tabs-inline">
              {[
                ["logs", `Output${mine.length ? ` · ${mine.length}` : ""}`],
                ["spec", "Spec"],
              ].map(([id, label]) => (
                <button key={id} className={cx("tab", { active: tab === id })} onClick={() => setTab(id)}>
                  {label}
                </button>
              ))}
            </nav>
            {tab === "logs" && (
              <>
                <input className="filter-input" placeholder="Filter output…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Filter output" />
                <button className="icon-btn" title="Copy" onClick={() => navigator.clipboard?.writeText(text())}>
                  <Copy size={14} />
                </button>
                <button className="icon-btn" title="Download" onClick={download}>
                  <Download size={14} />
                </button>
              </>
            )}
          </header>
          {tab === "logs" ? (
            <pre className="log trace" ref={logRef}>
              {mine.length === 0
                ? run
                  ? `no output from ${step.id} in this ${run.mode}`
                  : "no run selected"
                : mine.map((e, i) => (
                    <div key={e.seq} className={cx("ln", lineClass(e))}>
                      <span className="ln-num">{i + 1}</span>
                      <span className="ln-ts">{fmtTime(e.ts)}</span>
                      <span className="ln-text">
                        {e.kind !== "log" && <span className="ln-kind">{e.kind}</span>}
                        {e.message || " "}
                      </span>
                    </div>
                  ))}
            </pre>
          ) : (
            <pre className="log yaml">{specText(step)}</pre>
          )}
        </div>

        <aside className="job-side">
          <header className="job-side-head">
            <StatusIcon status={state} size={26} />
            <div className="inspector-title">
              <h2 className="mono">{step.id}</h2>
              <span className="muted small">
                {STEP_TYPE[step.type] ?? step.type} · stage {step.stage}
              </span>
            </div>
            <button className="icon-btn" onClick={onClose} aria-label="Close">
              <X size={16} />
            </button>
          </header>

          {state === "waiting" && (
            <div className="job-manual">
              <div>
                <strong>Manual step.</strong> {step.type === "db_migration" ? "Copying PHI data needs a person to start it, per the knowledge base." : "Waiting for someone to press play."}
              </div>
              <button className="btn btn-primary" onClick={() => onPlay(step.id)} disabled={busy}>
                <Play size={14} /> Run this step
              </button>
            </div>
          )}

          <dl className="job-rows">
            <Row label="Status">
              <Pill tone={STATUS[state]?.tone ?? "grey"}>{STATUS[state]?.label ?? state}</Pill>
            </Row>
            <Row label="Repository">
              <a className="mono link" href={githubUrl(step.repo, shas)} target="_blank" rel="noreferrer">
                {shortRepo(step.repo)} @ {sha ?? step.repo.split("@")[1] ?? "main"} <ExternalLink size={11} />
              </a>
              {!sha && <span className="muted small"> locked at Build</span>}
            </Row>
            {step.path && (
              <Row label="Terraform">
                <a className="mono link" href={githubUrl(step.repo, shas, step.path)} target="_blank" rel="noreferrer">
                  {step.path}/ <ExternalLink size={11} />
                </a>
              </Row>
            )}
            {step.entrypoint && (
              <Row label="Entrypoint">
                <a className="mono link" href={githubUrl(step.repo, shas, step.entrypoint)} target="_blank" rel="noreferrer">
                  {step.entrypoint} <ExternalLink size={11} />
                </a>
              </Row>
            )}
            {step.verify && (
              <Row label="Verified by">
                <a className="mono link" href={githubUrl(step.repo, shas, step.verify)} target="_blank" rel="noreferrer">
                  {step.verify} <ExternalLink size={11} />
                </a>
              </Row>
            )}
            <Row label="Undo">{step.rollback ? <span className="mono">{step.rollback}</span> : <span className="muted">nothing to undo (read-only)</span>}</Row>
            {step.needs?.length > 0 && <Row label="Needs">{step.needs.join(", ")}</Row>}
            {step.when === "manual" && <Row label="Trigger">Manual: press ▶ in Rehearse and Deploy</Row>}
            <Row label="Code written by">
              {step.codegen === "llm" ? (
                <span className="ai-badge">
                  <Bot size={12} /> the LLM, as a reviewed PR
                </span>
              ) : (
                "engineers"
              )}
            </Row>
            {env && (
              <Row label="Environment">
                {env} · resources named <span className="mono">mac-claims-{env}-…</span>
              </Row>
            )}
            {waits.length > 0 && (
              <Row label="Waits for">
                <ul className="plain approvals-list">
                  {waits.map(({ id, a, r }) => {
                    const st = r?.status ?? (a?.ticket ? "pending" : "unknown");
                    return (
                      <li key={id}>
                        <Pill tone={STATUS[st]?.tone ?? "grey"}>{st === "pending" ? "Pending" : STATUS[st]?.label ?? st}</Pill> <span className="mono">{id}</span>
                        {a && <span className="muted"> · {a.approver}</span>}
                        {(a?.ticket?.url || r?.url) && (
                          <>
                            {" · "}
                            <a className="link mono" href={a?.ticket?.url ?? r.url} target="_blank" rel="noreferrer">
                              {a?.ticket?.key ?? r.ticket}
                            </a>
                          </>
                        )}
                        {r?.detail && !a?.ticket && <div className="muted small">{r.detail}</div>}
                      </li>
                    );
                  })}
                </ul>
                <div className="muted small">Only Deploy waits for approvals; Rehearse doesn't.</div>
              </Row>
            )}
            {step.sources?.length > 0 && (
              <Row label="Sources">
                <ul className="plain sources">
                  {step.sources.map((s) => (
                    <li key={s.id ?? s}>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.title ?? s.id}</a> : <span className="mono small">{s.id ?? s}</span>}</li>
                  ))}
                </ul>
              </Row>
            )}
          </dl>
        </aside>
      </div>
    </section>
  );
}
