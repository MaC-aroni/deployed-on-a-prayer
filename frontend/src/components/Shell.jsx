import { createContext, useContext, useEffect, useState } from "react";
import { Activity, ChevronRight, Github, Hammer, PanelLeft, Presentation, Search, Sparkles, Workflow, Wand2 } from "lucide-react";
import { SIGN_IN_URL, api, signOut } from "../mac/api.js";
import { Link, usePath } from "../router.jsx";
import { cx } from "../lib.js";

const NAV = [
  {
    section: "Build",
    items: [
      { to: "/migrate", label: "Migrate", Icon: Wand2, match: (p) => p.startsWith("/migrate") },
      { to: "/migrations", label: "Pipelines", Icon: Workflow, match: (p) => p === "/" || p.startsWith("/migrations") || p.startsWith("/plans") },
    ],
  },
  {
    section: "Observe",
    items: [
      { to: "/runs", label: "Runs", Icon: Activity, match: (p) => p.startsWith("/runs") },
      { to: "/demo", label: "Pitch demo", Icon: Presentation, match: (p) => p.startsWith("/demo") },
    ],
  },
];

const COLLAPSE_KEY = "mac.sidebar.collapsed";

function readCollapsed() {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

// Who is signed in (GET /api/auth/me). `locked` means the server will refuse POSTs until the
// person signs in; the UI only greys buttons as a hint, the server decides.
const AuthContext = createContext({ me: null, locked: false });

export function useAuth() {
  return useContext(AuthContext);
}

const SIGN_IN_PROBLEMS = {
  "no-access": "That GitHub account can't push to the repo, so it can't run pipelines.",
  expired: "The sign-in took too long or was started in another tab. Try again.",
  failed: "GitHub didn't complete the sign-in. Try again.",
};

function Account({ me }) {
  if (!me || (!me.required && !me.login)) return null; // locally: no sign-in
  if (me.login) {
    return (
      <span className="account">
        <span className="avatar">{me.login[0].toUpperCase()}</span>
        <span>@{me.login}</span>
        <button className="link-btn" onClick={signOut}>
          Sign out
        </button>
      </span>
    );
  }
  if (!me.available) return <span className="muted small">Sign-in isn't set up here</span>;
  return (
    <a className="btn btn-github" href={SIGN_IN_URL}>
      <Github size={14} /> Sign in with GitHub
    </a>
  );
}

export default function Shell({ crumbs = [], actions, children }) {
  const path = usePath();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [me, setMe] = useState(null);
  const [signinProblem, setSigninProblem] = useState(() => {
    const p = new URLSearchParams(window.location.search).get("signin");
    return p ? SIGN_IN_PROBLEMS[p] || "Sign-in failed." : null;
  });

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* per-viewer convenience only */
    }
  }, [collapsed]);

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch(() => setMe({ login: null, required: false, available: false }));
    if (window.location.search.includes("signin=")) window.history.replaceState(null, "", window.location.pathname);
  }, []);

  const locked = Boolean(me?.required && !me.login);

  return (
    <AuthContext.Provider value={{ me, locked }}>
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

          {NAV.map((group) => (
            <div key={group.section}>
              <div className="nav-section">
                {group.section === "Build" && <Hammer size={11} />} {group.section}
              </div>
              <nav className="nav">
                {group.items.map(({ to, label, Icon, match }) => (
                  <Link key={to} to={to} className={cx("nav-item", { active: match(path) })} title={label}>
                    <Icon size={16} />
                    <span>{label}</span>
                  </Link>
                ))}
              </nav>
            </div>
          ))}

          <div className="sidebar-foot">
            <div className="env">
              <span className="env-dot" />
              <span>Prayerwell Health · AWS</span>
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
              {actions}
              <Account me={me} />
            </div>
          </header>
          <div className="content">
            {signinProblem && (
              <div className="banner tone-red" onClick={() => setSigninProblem(null)}>
                {signinProblem}
              </div>
            )}
            {locked && me?.available && (
              <div className="banner tone-blue">
                You can watch everything. To run a pipeline, <a href={SIGN_IN_URL}>sign in with GitHub</a>. Buttons here make real AWS, Jira and Confluence changes.
              </div>
            )}
            {children}
          </div>
        </div>
      </div>
    </AuthContext.Provider>
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

// A small confirmation that doesn't block the page (no window.confirm: it freezes automation).
export function Confirm({ text, onYes, onNo, busy }) {
  return (
    <div className="confirm" role="alertdialog">
      <span>{text}</span>
      <button className="btn btn-primary" onClick={onYes} disabled={busy}>
        Yes, go
      </button>
      <button className="btn" onClick={onNo}>
        Cancel
      </button>
    </div>
  );
}
