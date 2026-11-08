import { Check, Circle, CircleHelp, Hand, LoaderCircle, Lock, Minus, Play, TriangleAlert, Undo2, X } from "lucide-react";
import working from "../assets/greenloading.gif";
import { STATUS } from "../status.js";
import { cx } from "../lib.js";

// An agent at work. Wherever a Nemotron agent is running this replaces the status dot; clicking
// it opens the agent hierarchy for that run (the page at /agents/:runId).
export function AgentIcon({ size = 24, onClick, title = "Agent working · open the agent view", className }) {
  // A span, not a button: it sits inside the step card, which is a button already.
  return (
    <span
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      className={cx("agent-icon", { clickable: Boolean(onClick) }, className)}
      style={{ "--s": `${size}px` }}
      title={title}
      aria-label={title}
      onClick={
        onClick &&
        ((e) => {
          e.stopPropagation();
          e.preventDefault();
          onClick(e);
        })
      }
      onKeyDown={onClick && ((e) => e.key === "Enter" && (e.stopPropagation(), onClick(e)))}
    >
      <img src={working} alt="" width={size} height={size} />
    </span>
  );
}

const ICONS = {
  succeeded: Check,
  approved: Check,
  failed: X,
  rejected: X,
  running: LoaderCircle,
  pending: Circle,
  blocked: Lock,
  waiting: Play,
  manual: Hand,
  rolled_back: Undo2,
  rollback_failed: TriangleAlert,
  skipped: Minus,
  unknown: CircleHelp,
};

// GitLab-style status badge: tinted ring, solid core, white glyph.
export default function StatusIcon({ status, size = 24, agent = false, title, className, onAgent }) {
  const key = STATUS[status] ? status : "pending";
  if (agent && key === "running") return <AgentIcon size={Math.max(size, 18)} onClick={onAgent} className={className} />;
  const Icon = ICONS[key] ?? Circle;
  const meta = STATUS[key];
  const tone = key === "running" && agent ? "violet" : meta.tone;
  return (
    <span
      className={cx("status", `tone-${tone}`, `is-${key}`, className)}
      style={{ "--s": `${size}px` }}
      title={title ?? meta.label}
      aria-label={meta.label}
    >
      <Icon size={Math.round(size * 0.5)} strokeWidth={3} className={key === "running" ? "spin" : undefined} />
    </span>
  );
}

export function Pill({ tone = "grey", children, className, title }) {
  return (
    <span className={cx("pill", `tone-${tone}`, className)} title={title}>
      {children}
    </span>
  );
}
