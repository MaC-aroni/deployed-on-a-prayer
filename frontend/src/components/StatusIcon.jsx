import { Check, Circle, CircleHelp, Hand, LoaderCircle, Lock, Minus, Play, TriangleAlert, Undo2, X } from "lucide-react";
import { STATUS } from "../status.js";
import { cx } from "../lib.js";

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
export default function StatusIcon({ status, size = 24, agent = false, title, className }) {
  const key = STATUS[status] ? status : "pending";
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
