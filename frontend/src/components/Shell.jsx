import { useEffect, useState } from "react";
import { Activity, ChevronRight, KeyRound, PanelLeft, Presentation, Search, Sparkles, Workflow } from "lucide-react";
import { getToken, setToken } from "../api.js";
import { Link, usePath } from "../router.jsx";
import { cx } from "../lib.js";

const NAV = [
  { to: "/migrations", label: "Migrations", Icon: Workflow, match: (p) => p === "/" || p.startsWith("/migrations") },
  { to: "/runs", label: "Runs", Icon: Activity, match: (p) => p.startsWith("/runs") },
  { to: "/demo", label: "Pitch demo", Icon: Presentation, match: (p) => p.startsWith("/demo") },
];

const COLLAPSE_KEY = "mac.sidebar.collapsed";

function readCollapsed() {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

function TokenBox() {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(getToken);
  const has = Boolean(getToken());
  function save() {
    setToken(value.trim());
    setOpen(false);
  }
  return (
    <div className="token">
      <button className="token-toggle" onClick={() => setOpen((v) => !v)} title="MaC API token (only needed on Fly)">
        <KeyRound size={14} />
        <span>{has ? "API token set" : "API token"}</span>
      </button>
      {open && (
        <form
          className="token-form"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <input type="password" placeholder="Bearer token for /api/mac on Fly" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" />
          <button className="btn" type="submit">
            Save
          </button>
        </form>
      )}
    </div>
  );
}

export default function Shell({ crumbs = [], actions, children }) {
  const path = usePath();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* per-viewer convenience only */
    }
  }, [collapsed]);

  return (
    <div className={cx("shell", { collapsed })}>
      <aside className="sidebar">
        <Link to="/" className="brand" title="MaC · Migration as Code">
          <span className="brand-mark">
            <Sparkles size={14} strokeWidth={2.5} />
          </span>
          <span className="brand-text">
            <strong>MaC</strong>
            <span>Migration as Code</span>
          </span>
        </Link>

        <label className="search">
          <Search size={15} />
          <input placeholder="Search or go to…" />
          <kbd>/</kbd>
        </label>

        <div className="nav-section">Prayerwell Health</div>
        <nav className="nav">
          {NAV.map(({ to, label, Icon, match }) => (
            <Link key={to} to={to} className={cx("nav-item", { active: match(path) })} title={label}>
              <Icon size={16} />
              <span>{label}</span>
            </Link>
          ))}
        </nav>

        <div className="sidebar-foot">
          <TokenBox />
          <div className="who">
            <span className="avatar">E</span>
            <span>Elathius</span>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-btn" onClick={() => setCollapsed((v) => !v)} aria-label="Toggle sidebar" title="Toggle sidebar">
              <PanelLeft size={15} />
            </button>
            <nav className="crumbs">
              {crumbs.map((c, i) => (
                <span key={i} className="crumb">
                  {i > 0 && <ChevronRight size={14} className="crumb-sep" />}
                  {c.to ? <Link to={c.to}>{c.label}</Link> : <span className="crumb-current">{c.label}</span>}
                </span>
              ))}
            </nav>
          </div>
          <div className="topbar-actions">{actions}</div>
        </header>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}

export function EmptyState({ title, body, children }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {body && <p>{body}</p>}
      {children}
    </div>
  );
}
