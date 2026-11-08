import { useEffect, useState } from "react";
import { OctagonX } from "lucide-react";
import { api } from "../mac/api.js";
import { cx } from "../lib.js";

// Cancel a run from a list row. Two presses: the first arms the button and names what will
// happen (the runner stops the run and undoes everything it did), the second sends it. The
// server decides whether the run can still be cancelled; its answer is shown as written.
const CANCELLABLE = new Set(["running", "waiting"]);

export function canCancel(run) {
  return Boolean(run && CANCELLABLE.has(run.status));
}

export default function CancelButton({ run, onDone, className }) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!armed) return undefined;
    const id = setTimeout(() => setArmed(false), 5000);
    return () => clearTimeout(id);
  }, [armed]);

  if (!canCancel(run)) return null;

  const onClick = async (e) => {
    e.stopPropagation();
    e.preventDefault();
    setError(null);
    if (!armed) {
      setArmed(true);
      return;
    }
    setBusy(true);
    try {
      await api.cancel(run.id);
      setArmed(false);
      onDone?.();
    } catch (err) {
      setError(err?.detail ?? err?.message ?? "Cancel failed");
    } finally {
      setBusy(false);
    }
  };

  // Rows are buttons themselves, so this is a span with the button role: a button inside a
  // button is invalid HTML and the browser drops the inner one's clicks.
  const onKey = (e) => {
    if (e.key === "Enter" || e.key === " ") onClick(e);
  };
  return (
    <span className={cx("cancel-run", className)} onClick={(e) => e.stopPropagation()}>
      <span
        role="button"
        tabIndex={busy ? -1 : 0}
        aria-disabled={busy || undefined}
        aria-pressed={armed}
        className={cx("btn btn-ghost row-action", { "btn-danger": armed, disabled: busy })}
        onClick={busy ? undefined : onClick}
        onKeyDown={busy ? undefined : onKey}
        title={armed ? "Press again: the runner stops this run and undoes everything it did" : "Stop this run and undo what it did"}
      >
        <OctagonX size={13} />
        {busy ? "Cancelling…" : armed ? "Stop and undo?" : "Cancel"}
      </span>
      {error && (
        <span className="small tone-red cancel-error" role="alert">
          {error}
        </span>
      )}
    </span>
  );
}
