import { useEffect, useRef, useState } from "react";
import { MoreHorizontal } from "lucide-react";
import { cx } from "../lib.js";

// The ··· menu: every action that isn't the page's one primary action lives here.
// items: [{ label, hint, onClick, disabled, danger, group }] or { separator: true } or { heading }
export default function Menu({ items, label = "More actions", footer, children }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const close = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const key = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  return (
    <div className="menu" ref={ref}>
      <button className="icon-btn" aria-haspopup="menu" aria-expanded={open} aria-label={label} onClick={() => setOpen((v) => !v)}>
        <MoreHorizontal size={16} />
      </button>
      {open && (
        <div className="menu-pop" role="menu">
          {items.map((it, i) =>
            it.separator ? (
              <div className="menu-sep" key={`sep-${i}`} />
            ) : it.heading ? (
              <div className="menu-heading" key={`h-${i}`}>
                {it.heading}
              </div>
            ) : (
              <button
                key={it.label}
                role="menuitem"
                className={cx("menu-item", { danger: it.danger, hint: it.hint })}
                disabled={it.disabled}
                title={it.title}
                onClick={() => {
                  setOpen(false);
                  it.onClick?.();
                }}
              >
                {it.icon}
                <span className="menu-label">{it.label}</span>
                {it.detail && <span className="menu-detail">{it.detail}</span>}
              </button>
            ),
          )}
          {footer}
          {children}
        </div>
      )}
    </div>
  );
}
