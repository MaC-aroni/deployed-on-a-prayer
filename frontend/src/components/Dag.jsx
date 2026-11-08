import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Hand, Lock, RotateCw, Sparkles } from "lucide-react";
import StatusIcon from "./StatusIcon.jsx";
import { STAGES, stageStatusAt, statusAt } from "../data/mock.js";
import { cx } from "../lib.js";

const GUTTER = 22; // room on the left of each column for same-column edges

function adjacency(steps) {
  const parents = {};
  const children = {};
  for (const s of steps) {
    parents[s.id] = s.needs;
    for (const n of s.needs) (children[n] ||= []).push(s.id);
  }
  return { parents, children };
}

function collect(id, map) {
  const out = new Set();
  const stack = [id];
  while (stack.length) {
    const cur = stack.pop();
    for (const next of map[cur] ?? []) if (!out.has(next)) (out.add(next), stack.push(next));
  }
  return out;
}

function edgePath(a, b, sameColumn) {
  if (!sameColumn) {
    const x1 = a.x + a.w;
    const y1 = a.y + a.h / 2;
    const x2 = b.x;
    const y2 = b.y + b.h / 2;
    const dx = Math.max(28, (x2 - x1) * 0.55);
    return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
  }
  const x = a.x;
  const y1 = a.y + a.h / 2;
  const y2 = b.y + b.h / 2;
  const bulge = x - GUTTER * 1.5;
  return `M${x},${y1} C${bulge},${y1} ${bulge},${y2} ${x},${y2}`;
}

function Aside({ step, status }) {
  if (step.type === "agent") return <Sparkles size={14} className="node-aside nemotron" />;
  if (step.type === "approval") return <Lock size={14} className="node-aside" />;
  if (step.gate === "manual") return <Hand size={14} className="node-aside" />;
  if (status === "failed" || status === "rolled_back") return <RotateCw size={14} className="node-aside" />;
  return <span className="node-aside" />;
}

export default function Dag({ steps, t, selectedId, onSelect, showDeps = true, fit = true }) {
  const outerRef = useRef(null);
  const canvasRef = useRef(null);
  const nodeEls = useRef(new Map());
  const [geo, setGeo] = useState({ w: 0, h: 0, boxes: {} });
  const [avail, setAvail] = useState(0);
  const [hover, setHover] = useState(null);

  const { parents, children } = useMemo(() => adjacency(steps), [steps]);
  const columnOf = useMemo(() => Object.fromEntries(steps.map((s) => [s.id, s.stage])), [steps]);
  const edges = useMemo(() => steps.flatMap((s) => s.needs.map((n) => ({ from: n, to: s.id }))), [steps]);

  // Lineage follows the hovered node only; selection is shown with a ring.
  const lineage = useMemo(() => {
    if (!hover) return null;
    return new Set([hover, ...collect(hover, parents), ...collect(hover, children)]);
  }, [hover, parents, children]);

  const measure = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const boxes = {};
    nodeEls.current.forEach((el, id) => {
      if (el) boxes[id] = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
    });
    setGeo({ w: canvas.scrollWidth, h: canvas.scrollHeight, boxes });
    if (outerRef.current) setAvail(outerRef.current.clientWidth);
  }, []);

  useLayoutEffect(measure, [measure, steps]);
  useEffect(() => {
    const ro = new ResizeObserver(measure);
    if (outerRef.current) ro.observe(outerRef.current);
    if (canvasRef.current) ro.observe(canvasRef.current);
    document.fonts?.ready.then(measure);
    return () => ro.disconnect();
  }, [measure]);

  // Shrink to fit, but never below a readable size; past that the canvas scrolls.
  const scale = fit && geo.w > 0 && avail > 0 ? Math.max(0.62, Math.min(1, avail / geo.w)) : 1;

  return (
    <div className="dag-outer" ref={outerRef} style={{ height: geo.h ? geo.h * scale : undefined }}>
      <div className="dag-canvas" ref={canvasRef} style={{ transform: `scale(${scale})` }}>
        {showDeps && (
          <svg className="dag-edges" width={geo.w} height={geo.h} aria-hidden>
            {edges.map(({ from, to }) => {
              const a = geo.boxes[from];
              const b = geo.boxes[to];
              if (!a || !b) return null;
              const lit = lineage ? lineage.has(from) && lineage.has(to) : false;
              const dim = lineage ? !lit : false;
              return (
                <path
                  key={`${from}->${to}`}
                  d={edgePath(a, b, columnOf[from] === columnOf[to])}
                  className={cx("edge", { lit, dim })}
                />
              );
            })}
          </svg>
        )}

        {STAGES.map((stage) => {
          const inStage = steps.filter((s) => s.stage === stage.id);
          return (
            <section className="col" key={stage.id}>
              <header className="col-head">
                <StatusIcon status={stageStatusAt(stage.id, t)} size={16} />
                <span className="col-name">{stage.name}</span>
                <span className="col-count">{inStage.length}</span>
              </header>
              <div className="col-card">
                {inStage.map((step) => {
                  const status = statusAt(step, t);
                  const dim = lineage ? !lineage.has(step.id) : false;
                  return (
                    <button
                      key={step.id}
                      type="button"
                      ref={(el) => nodeEls.current.set(step.id, el)}
                      className={cx("node", `is-${status}`, { selected: step.id === selectedId, dim, agent: step.type === "agent" })}
                      onClick={() => onSelect(step.id)}
                      onMouseEnter={() => setHover(step.id)}
                      onMouseLeave={() => setHover(null)}
                    >
                      <StatusIcon status={status} size={26} agent={step.type === "agent"} />
                      <span className="node-text">
                        <span className="node-name">{step.name}</span>
                        <span className="node-sub">{step.sub}</span>
                      </span>
                      <Aside step={step} status={status} />
                    </button>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
