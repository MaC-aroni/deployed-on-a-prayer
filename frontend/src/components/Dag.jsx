import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import StatusIcon from "./StatusIcon.jsx";
import { cx } from "../lib.js";

// Generic pipeline graph: columns of step cards with bezier dependency edges.
//   columns: [{ id, name, status, steps: [{ id, name, sub, status, agent, aside }] }]
//   edges:   [{ from, to }]  (step ids)
// Same-column edges route through a gutter on the column's left.

const GUTTER = 28;

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

export default function Dag({ columns, edges, selectedId, onSelect, showDeps = true, fit = true, minScale = 0.92, emptyHint, failedId = null, onAgent }) {
  const outerRef = useRef(null);
  const canvasRef = useRef(null);
  const nodeEls = useRef(new Map());
  const [geo, setGeo] = useState({ w: 0, h: 0, boxes: {} });
  const [avail, setAvail] = useState(0);
  const [hover, setHover] = useState(null);

  const columnOf = useMemo(() => {
    const m = {};
    for (const c of columns) for (const s of c.steps) m[s.id] = c.id;
    return m;
  }, [columns]);

  const { parents, children } = useMemo(() => {
    const parents = {};
    const children = {};
    for (const { from, to } of edges) {
      (parents[to] ||= []).push(from);
      (children[from] ||= []).push(to);
    }
    return { parents, children };
  }, [edges]);

  const lineage = useMemo(() => {
    if (!hover) return null;
    return new Set([hover, ...collect(hover, parents), ...collect(hover, children)]);
  }, [hover, parents, children]);

  // Where the run broke: the failed step and everything that depended on it.
  const broken = useMemo(() => (failedId ? new Set([failedId, ...collect(failedId, children)]) : new Set()), [failedId, children]);

  const measure = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const boxes = {};
    nodeEls.current.forEach((el, id) => {
      if (el) boxes[id] = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
    });
    // offset*, not scroll*: the absolutely positioned edge layer keeps the old size until this runs
    setGeo({ w: canvas.offsetWidth, h: canvas.offsetHeight, boxes });
    if (outerRef.current) setAvail(outerRef.current.clientWidth);
  }, []);

  useLayoutEffect(measure, [measure, columns]);
  useEffect(() => {
    const ro = new ResizeObserver(measure);
    if (outerRef.current) ro.observe(outerRef.current);
    if (canvasRef.current) ro.observe(canvasRef.current);
    document.fonts?.ready.then(measure);
    return () => ro.disconnect();
  }, [measure]);

  // Shrink to fit, but never below a readable size; past that the canvas scrolls.
  const scale = fit && geo.w > 0 && avail > 0 ? Math.max(minScale, Math.min(1, avail / geo.w)) : 1;

  if (!columns.length) return <div className="dag-empty muted">{emptyHint ?? "Nothing to draw."}</div>;

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
              const cut = broken.has(from) && broken.has(to);
              return <path key={`${from}->${to}`} d={edgePath(a, b, columnOf[from] === columnOf[to])} className={cx("edge", { lit, dim, cut })} />;
            })}
          </svg>
        )}

        {columns.map((col) => (
          <section className={cx("col", { "col-broke": failedId && col.steps.some((s) => s.id === failedId) })} key={col.id}>
            <header className="col-head">
              <StatusIcon status={col.status ?? "pending"} size={16} />
              <span className="col-name">{col.name}</span>
              <span className="col-count">{failedId && col.steps.some((s) => s.id === failedId) ? "failed here" : col.steps.length}</span>
            </header>
            <div className="col-card">
              {col.steps.map((step) => {
                const dim = lineage ? !lineage.has(step.id) : false;
                return (
                  <button
                    key={step.id}
                    type="button"
                    ref={(el) => nodeEls.current.set(step.id, el)}
                    className={cx("node", `is-${step.status}`, { selected: step.id === selectedId, dim, agent: step.agent, breakpoint: step.breakpoint, broke: step.id === failedId, after: broken.has(step.id) && step.id !== failedId && (step.status === "pending" || step.status === "skipped") })}
                    onClick={() => onSelect?.(step.id)}
                    onMouseEnter={() => setHover(step.id)}
                    onMouseLeave={() => setHover(null)}
                  >
                    <StatusIcon status={step.status} size={32} agent={step.agent} onAgent={onAgent && (() => onAgent(step.id))} />
                    <span className="node-text">
                      <span className="node-name">{step.name}</span>
                      {step.sub && <span className="node-sub">{step.sub}</span>}
                    </span>
                    <span className="node-aside">{step.aside}</span>
                  </button>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
