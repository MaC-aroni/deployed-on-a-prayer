import { Check, Circle, Hand, LoaderCircle, Lock, Minus, Undo2, X } from "lucide-react";
import { STATUS } from "../data/mock.js";
import { cx } from "../lib.js";

const ICONS = {
  succeeded: Check,
  approved: Check,
  failed: X,
  running: LoaderCircle,
  pending: Circle,
  blocked: Lock,
  manual: Hand,
  rolled_back: Undo2,
  skipped: Minus,
};

// GitLab-style status badge: tinted ring, solid core, white glyph.
export default function StatusIcon({ status, size = 24, agent = false, title, className }) {
  const Icon = ICONS[status] ?? Circle;
  const meta = STATUS[status] ?? STATUS.pending;
  const tone = status === "running" && agent ? "violet" : meta.tone;
  return (
    <span
      className={cx("status", `tone-${tone}`, `is-${status}`, className)}
      style={{ "--s": `${size}px` }}
      title={title ?? meta.label}
      aria-label={meta.label}
    >
      <Icon size={Math.round(size * 0.5)} strokeWidth={3} className={status === "running" ? "spin" : undefined} />
    </span>
  );
}

export function Pill({ tone = "grey", children, className }) {
  return <span className={cx("pill", `tone-${tone}`, className)}>{children}</span>;
}
