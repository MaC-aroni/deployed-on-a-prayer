import { APPROVAL_LABEL, RUN_LABEL, STEP_LABEL, VARIANT } from "../util.js";
import StatusIcon from "./StatusIcon.jsx";

// GitLab-style badge: light background, dark text, optional status icon.
export default function Badge({ status, label, icon = true, kind = "run", className = "" }) {
  const text = label || (kind === "approval" ? APPROVAL_LABEL[status] : kind === "step" ? STEP_LABEL[status] : RUN_LABEL[status]) || status;
  return (
    <span className={`badge badge-${VARIANT[status] || "neutral"} ${className}`}>
      {icon && status && <StatusIcon state={status} size={12} />}
      {text}
    </span>
  );
}
