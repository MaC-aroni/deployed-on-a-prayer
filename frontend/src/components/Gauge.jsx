import { cx } from "../lib.js";

// The stage gauge: the dial world's one signature move. A slim ring whose index marks are the
// pipeline's stages and whose hand points at the stage the run is in. While the run is active
// a thin seconds hand sweeps; otherwise everything is still. Pure SVG, no library.
//   stages: [{ name, status }] in run order; status is a step/run state (pending, running,
//   waiting, blocked, succeeded, failed, rolled_back, skipped, cancelled …).

const ACTIVE = new Set(["running", "waiting", "blocked", "rolling_back"]);
const DONE = new Set(["succeeded", "approved"]);
const BAD = new Set(["failed", "rollback_failed"]);

function polar(cx0, cy0, r, deg) {
  const a = ((deg - 90) * Math.PI) / 180;
  return [cx0 + r * Math.cos(a), cy0 + r * Math.sin(a)];
}

export function currentIndex(stages) {
  const active = stages.findIndex((s) => ACTIVE.has(s.status));
  if (active >= 0) return active;
  const bad = stages.findIndex((s) => BAD.has(s.status));
  if (bad >= 0) return bad;
  let last = -1;
  stages.forEach((s, i) => {
    if (DONE.has(s.status) || s.status === "rolled_back") last = i;
  });
  return last;
}

// `runStatus` tints the ring when per-stage states are unknown (list rows): the stages stay neutral
// index marks and the ring says how the run ended.
export default function Gauge({ stages = [], size = 56, active = false, tone = "accent", runStatus = null, title, className }) {
  const n = stages.length;
  const c = size / 2;
  const r = c - 3;
  const span = 300; // degrees of dial used, leaving a gap at the bottom like a power reserve
  const start = -span / 2;
  const at = (i) => (n <= 1 ? 0 : start + (span * i) / (n - 1));
  const idx = currentIndex(stages);
  const handDeg = idx < 0 ? start : at(idx);
  const label = title ?? (idx >= 0 ? `${stages[idx].name} · ${stages[idx].status}` : "not started");
  return (
    <svg className={cx("gauge", `tone-${tone}`, { active }, runStatus && `run-${runStatus}`, className)} width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label}>
      <title>{label}</title>
      <circle className="gauge-ring" cx={c} cy={c} r={r} />
      {stages.map((s, i) => {
        const [x1, y1] = polar(c, c, r, at(i));
        const [x2, y2] = polar(c, c, r - (i === idx ? size * 0.2 : size * 0.14), at(i));
        return <line key={s.name ?? i} className={cx("gauge-mark", `is-${s.status}`, { current: i === idx })} x1={x1} y1={y1} x2={x2} y2={y2} />;
      })}
      {idx >= 0 && (
        <g className="gauge-hand" style={{ transform: `rotate(${handDeg}deg)`, transformOrigin: `${c}px ${c}px` }}>
          <line x1={c} y1={c + size * 0.08} x2={c} y2={c - r + size * 0.2} />
          <circle cx={c} cy={c} r={size * 0.045} />
        </g>
      )}
      {active && (
        <g className="gauge-sweep" style={{ transformOrigin: `${c}px ${c}px` }}>
          <line x1={c} y1={c} x2={c} y2={c - r + size * 0.28} />
        </g>
      )}
    </svg>
  );
}
