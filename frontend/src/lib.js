// Small shared helpers. No framework code here.

export function cx(...parts) {
  return parts
    .flatMap((p) => (p && typeof p === "object" ? Object.keys(p).filter((k) => p[k]) : p))
    .filter(Boolean)
    .join(" ");
}

export function fmtDuration(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return `${m}m ${String(rem).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, "0")}m`;
}

// Clock label for a run offset in seconds, anchored at the run's start time.
export function fmtClock(startHHMM, offsetSeconds) {
  const [h, m] = startHHMM.split(":").map(Number);
  const total = h * 3600 + m * 60 + Math.round(offsetSeconds);
  const hh = Math.floor(total / 3600) % 24;
  const mm = Math.floor((total % 3600) / 60);
  const ss = total % 60;
  return [hh, mm, ss].map((n) => String(n).padStart(2, "0")).join(":");
}
