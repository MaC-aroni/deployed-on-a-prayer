import { useEffect, useState } from "react";
import { Activity, ChevronRight, ListChecks, Network, PanelLeft, Plus, Search, Sparkles, Workflow } from "lucide-react";
import { Link, usePath } from "../router.jsx";
import { cx } from "../lib.js";

const NAV = [
  { to: "/migrations", label: "Migrations", Icon: Workflow, match: (p) => p === "/" || p.startsWith("/migrations") },
  { to: "/approvals", label: "Approvals", Icon: ListChecks, match: (p) => p.startsWith("/approvals") },
  { to: "/knowledge", label: "Knowledge graph", Icon: Network, match: (p) => p.startsWith("/knowledge") },
  { to: "/runs", label: "Runner", Icon: Activity, match: (p) => p.startsWith("/runs") },
];

const COLLAPSE_KEY = "mac.sidebar.collapsed";

function readCollapsed() {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

export default function Shell({ crumbs = [], children }) {
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

        <div className="nav-section">Project</div>
        <nav className="nav">
          {NAV.map(({ to, label, Icon, match }) => (
            <Link key={to} to={to} className={cx("nav-item", { active: match(path) })} title={label}>
              <Icon size={16} />
              <span>{label}</span>
            </Link>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="env">
            <span className="env-dot" />
            <span>
              AWS sandbox · <span className="mono">us-east-1</span>
            </span>
          </div>
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
          <div className="topbar-actions">
            <button className="btn btn-primary">
              <Plus size={15} />
              New migration
            </button>
          </div>
        </header>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}

export function EmptyState({ title, body }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {body && <p>{body}</p>}
    </div>
  );
}
