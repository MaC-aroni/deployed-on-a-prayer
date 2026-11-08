import { useEffect } from "react";

// A confirmation dialog. Rehearse, Deploy and Undo change real AWS, so they say what they'll do.
export default function Modal({ title, children, confirmLabel, danger, onConfirm, onCancel }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div className="modal-backdrop" onClick={onCancel} role="presentation">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head"><h2 id="modal-title">{title}</h2><button className="icon-btn" onClick={onCancel} aria-label="Close">✕</button></div>
        <div className="modal-body">{children}</div>
        <div className="modal-foot">
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className={`btn ${danger ? "btn-danger-solid" : "btn-confirm"}`} onClick={onConfirm} autoFocus>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
