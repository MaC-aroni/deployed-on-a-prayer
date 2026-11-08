import { useEffect, useMemo, useRef, useState } from "react";
import { STEP_TYPE, absTime, fmtDuration, githubUrl, planSummary, repoName, shortSha } from "../util.js";
import Badge from "./Badge.jsx";
import StatusIcon from "./StatusIcon.jsx";

// Colour Terraform plan output the way a diff reads.
function lineClass(e) {
  if (e.kind !== "log") return `tr-${e.kind}`;
  const t = e.message.trimStart();
  if (t.startsWith("+")) return "tr-add";
  if (t.startsWith("-") && !t.startsWith("--")) return "tr-del";
  if (t.startsWith("~")) return "tr-chg";
  if (t.startsWith("#")) return "tr-cmt";
  if (t.startsWith("$ ")) return "tr-cmd";
  if (/\b(error|failed|traceback)\b/i.test(t)) return "tr-err";
  return "";
}

export function JobLog({ run, events, step, onShowAll }) {
  const [query, setQuery] = useState("");
  const [stickBottom, setStickBottom] = useState(true);
  const box = useRef(null);
  const lines = useMemo(() => events.filter((e) => (step ? e.step === step : true) && e.kind !== "step" && (!query || e.message.toLowerCase().includes(query.toLowerCase()))), [events, step, query]);

  useEffect(() => {
    if (stickBottom && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines.length, stickBottom]);

  const onScroll = () => {
    const el = box.current;
    if (!el) return;
    setStickBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
  };
  const text = () => lines.map((e) => (!step && e.step ? `[${e.step}] ` : "") + e.message).join("\n");
  const download = () => {
    const blob = new Blob([text()], { type: "text/plain" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `${run.mode}-${run.id}${step ? `-${step}` : ""}.log` });
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <section className="trace">
      <div className="trace-bar">
        <strong>{step || "Run log"}</strong>
        <span className="muted">{lines.length} lines</span>
        {step && <button className="btn btn-sm" onClick={onShowAll}>Show whole run</button>}
        <span className="spacer" />
        <input className="input input-sm" placeholder="Filter output…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Filter log output" />
        <button className="btn btn-sm" onClick={() => navigator.clipboard?.writeText(text())}>Copy</button>
        <button className="btn btn-sm" onClick={download}>Download</button>
      </div>
      <div className="trace-body" ref={box} onScroll={onScroll}>
        {lines.length === 0 && <div className="trace-empty">{step ? "This step produced no output in this run." : "No output yet."}</div>}
        {lines.map((e, i) => (
          <div key={e.seq} className={`tr-line ${lineClass(e)}`}>
            <span className="tr-num">{i + 1}</span>
            <span className="tr-ts" title={absTime(e.ts)}>{new Date(e.ts * 1000).toLocaleTimeString([], { hour12: false })}</span>
            <span className="tr-text">{e.kind !== "log" && <span className="tr-kind">{e.kind}</span>}{!step && e.step && <span className="tr-step">{e.step}</span>}{e.message || " "}</span>
          </div>
        ))}
      </div>
      {!stickBottom && <button className="trace-jump" onClick={() => { setStickBottom(true); box.current.scrollTop = box.current.scrollHeight; }}>↓ Jump to latest</button>}
    </section>
  );
}

function Row({ label, children }) {
  return children == null || children === "" ? null : <div className="job-row"><dt>{label}</dt><dd>{children}</dd></div>;
}

export function JobDetails({ step, run, detail, timing, events, report, onPlay, locked }) {
  const state = run?.steps?.[step.id] || "none";
  const shas = run?.shas;
  const sha = shortSha(step.repo, shas);
  const approvals = step.requires_approval.map((id) => ({ id, a: detail.approvals.find((x) => x.id === id), r: report?.approvals?.[id] }));
  const plan = run?.mode === "build" ? planSummary(events, step.id) : null;
  const env = run?.mode === "deploy" ? "production" : run?.mode === "rehearse" ? "rehearsal" : null;
  return (
    <aside className="job-side">
      <div className="job-side-head">
        <StatusIcon state={state} size={22} />
        <div>
          <div className="job-side-title">{step.id}</div>
          <div className="muted small">{STEP_TYPE[step.type]} · stage {step.stage}</div>
        </div>
      </div>
      {state === "waiting" && (
        <div className="job-manual">
          <div><strong>Manual step.</strong> {step.type === "db_migration" ? "Copying PHI data needs a person to start it, per the knowledge base." : "Waiting for someone to press play."}</div>
          <button className="btn btn-confirm" disabled={locked} onClick={() => onPlay(step.id)} title={locked ? "Sign in to run steps" : ""}>▶ Run this step</button>
        </div>
      )}
      <dl className="job-rows">
        <Row label="Status"><Badge status={state} kind="step" /></Row>
        <Row label="Duration">{timing?.duration != null ? fmtDuration(timing.duration) : null}</Row>
        <Row label="Started">{timing?.started ? absTime(timing.started) : null}</Row>
        {plan && <Row label="Plan"><span className="plan-sum"><b className="tr-add">+{plan.add}</b> <b className="tr-chg">~{plan.change}</b> <b className="tr-del">−{plan.destroy}</b></span></Row>}
        <Row label="Repository">
          <a href={githubUrl(step.repo, shas)} target="_blank" rel="noreferrer" className="mono">{repoName(step.repo)}{sha ? ` @ ${sha}` : " @ main"}</a>
          {!sha && <span className="muted small"> (locked at Build)</span>}
        </Row>
        {step.path && <Row label="Terraform"><a href={githubUrl(step.repo, shas, step.path)} target="_blank" rel="noreferrer" className="mono">{step.path}/</a></Row>}
        {step.entrypoint && <Row label="Entrypoint"><a href={githubUrl(step.repo, shas, step.entrypoint)} target="_blank" rel="noreferrer" className="mono">{step.entrypoint}</a></Row>}
        {step.verify && <Row label="Verified by"><span className="mono">{step.verify}</span></Row>}
        <Row label="Undo">{step.rollback ? <span className="mono">{step.rollback}</span> : <span className="muted">nothing to undo (read-only)</span>}</Row>
        {step.needs.length > 0 && <Row label="Needs">{step.needs.join(", ")}</Row>}
        {step.when === "manual" && <Row label="Trigger">Manual (press ▶ in Rehearse and Deploy)</Row>}
        <Row label="Code written by">{step.codegen === "llm" ? <><span className="chip chip-ai">AI</span> the LLM, delivered as a reviewed PR</> : "engineers"}</Row>
        {env && <Row label="Environment">{env} · resources named <span className="mono">mac-claims-{env}-…</span></Row>}
        {approvals.length > 0 && (
          <Row label="Waits for">
            <ul className="plain">
              {approvals.map(({ id, a, r }) => (
                <li key={id}><Badge status={r?.ticket || r?.url || a?.ticket ? (r?.status || "pending") : "not_requested"} kind="approval" /> {id}{a && <span className="muted"> · {a.approver}</span>}{a?.ticket && <> · <a href={a.ticket.url} target="_blank" rel="noreferrer">{a.ticket.key}</a></>}</li>
              ))}
            </ul>
            <div className="muted small">Only Deploy waits for approvals; Rehearse doesn't.</div>
          </Row>
        )}
        {step.sources?.length > 0 && (
          <Row label="Sources">
            <ol className="plain sources">{step.sources.map((s) => <li key={s.id || s}>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.title || s.id}</a> : <span className="mono">{s.id || s}</span>}</li>)}</ol>
          </Row>
        )}
      </dl>
    </aside>
  );
}
