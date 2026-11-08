import { STEP_LABEL, VARIANT } from "../util.js";

// GitLab-style CI status icons: a 16x16 circle with a glyph, coloured by meaning. Drawn inline so
// they're crisp at every size and themeable through CSS variables.
const GLYPH = {
  succeeded: <path d="M4.5 8.2l2.3 2.3 4.7-4.9" />,
  approved: <path d="M4.5 8.2l2.3 2.3 4.7-4.9" />,
  failed: <path d="M5.3 5.3l5.4 5.4M10.7 5.3l-5.4 5.4" />,
  rejected: <path d="M5.3 5.3l5.4 5.4M10.7 5.3l-5.4 5.4" />,
  rollback_failed: <path d="M8 4.5v4.2M8 11.2v.3" />,
  waiting: <path d="M6.3 5.2v5.6l4.6-2.8z" fill="currentColor" stroke="none" />,
  blocked: <path d="M5.8 7.6V6.4a2.2 2.2 0 0 1 4.4 0v1.2M5.2 7.6h5.6v3.9H5.2z" />,
  pending: <path d="M6.3 5.5v5M9.7 5.5v5" />,
  skipped: <path d="M6 5.5L8.5 8 6 10.5M9 5.5L11.5 8 9 10.5" />,
  rolled_back: <path d="M10.9 6.2A3.4 3.4 0 1 0 11.4 9M11.2 4.6v2.1H9.1" />,
  undone: <path d="M10.9 6.2A3.4 3.4 0 1 0 11.4 9M11.2 4.6v2.1H9.1" />,
  running: null,
  none: null,
  unknown: <path d="M6.5 6.5a1.5 1.5 0 1 1 2.2 1.3c-.5.3-.7.6-.7 1.2M8 11v.3" />,
  not_requested: null,
};

export default function StatusIcon({ state = "none", size = 16, title, className = "" }) {
  const variant = VARIANT[state] || "neutral";
  const dashed = state === "none" || state === "pending" || state === "not_requested";
  return (
    <svg className={`ci-icon ci-${variant} ci-state-${state} ${className}`} width={size} height={size}
         viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"
         strokeLinejoin="round" role="img" aria-label={title || STEP_LABEL[state] || state}>
      {state === "running" ? (
        <>
          <circle cx="8" cy="8" r="6.5" className="ci-track" />
          <path d="M8 1.5a6.5 6.5 0 0 1 6.5 6.5" className="ci-spin" />
        </>
      ) : (
        <circle cx="8" cy="8" r="6.5" strokeDasharray={dashed && state !== "pending" ? "2.2 2.2" : undefined} />
      )}
      {GLYPH[state]}
    </svg>
  );
}
