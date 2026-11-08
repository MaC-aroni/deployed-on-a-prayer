import { useEffect, useRef, useState } from "react";
import { fmtDuration, stageState } from "../util.js";
import StatusIcon from "./StatusIcon.jsx";

function Job({ step, state, timing, selected, onSelect, onPlay, locked }) {
  const s = state || "none";
  const hint = `${step.type}${step.path ? ` · ${step.path}` : step.entrypoint ? ` · ${step.entrypoint}` : ""}`;
  return (
    <div className={`ci-job ci-job-${s} ${selected ? "selected" : ""}`} role="button" tabIndex={0}
         onClick={() => onSelect(step.id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(step.id); } }}
         title={hint}>
      <StatusIcon state={s} size={18} />
      <span className="ci-job-name">{step.id}</span>
      <span className="ci-job-meta">
        {step.codegen === "llm" && <span className="chip chip-ai" title="codegen: llm — the LLM writes this step's code, as a reviewed PR">AI</span>}
        {step.when === "manual" && s !== "waiting" && <span className="chip" title="Manual step: waits for ▶">manual</span>}
        {step.requires_approval.length > 0 && <span className="chip" title={`Needs approval: ${step.requires_approval.join(", ")}`}>🔒 {step.requires_approval.length}</span>}
        {timing?.duration != null && <span className="ci-job-time">{fmtDuration(timing.duration)}</span>}
      </span>
      {s === "waiting" && !locked && (
        <button className="ci-play" onClick={(e) => { e.stopPropagation(); onPlay(step.id); }} title="Run this manual step" aria-label={`Run ${step.id}`}>
          <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9-5.5z" fill="currentColor" /></svg>
        </button>
      )}
    </div>
  );
}

export default function PipelineGraph({ detail, run, timings, selected, onSelect, onPlay, locked }) {
  const box = useRef(null);
  const [edges, setEdges] = useState("");
  // Wide pipelines scroll sideways, like GitLab's. Fade the edges that have more behind them.
  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const update = () => {
      const more = el.scrollWidth - el.clientWidth > 4;
      setEdges(!more ? "" : `${el.scrollLeft > 4 ? "fade-l " : ""}${el.scrollLeft + el.clientWidth < el.scrollWidth - 4 ? "fade-r" : ""}`);
    };
    update();
    el.addEventListener("scroll", update);
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => { el.removeEventListener("scroll", update); ro.disconnect(); };
  }, [detail]);
  return (
    <div className={`ci-graph-wrap ${edges}`}>
    <div className="ci-graph" role="list" ref={box}>
      {detail.stages.map((stage, i) => (
        <div className={`ci-stage ${i < detail.stages.length - 1 ? "has-next" : ""}`} key={stage.name} role="listitem">
          <div className="ci-stage-head">
            <StatusIcon state={stageState(stage, run)} size={16} />
            <span className="ci-stage-name">{stage.name}</span>
          </div>
          <div className="ci-stage-jobs">
            {stage.steps.map((step) => (
              <Job key={step.id} step={step} state={run?.steps?.[step.id]} timing={timings?.[step.id]}
                   selected={selected === step.id} onSelect={onSelect} onPlay={onPlay} locked={locked} />
            ))}
          </div>
        </div>
      ))}
    </div>
    </div>
  );
}
