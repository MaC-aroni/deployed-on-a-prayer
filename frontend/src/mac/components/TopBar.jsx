import { SIGN_IN_URL, signOut } from "../api.js";

function Account({ me }) {
  if (!me || (!me.required && !me.login)) return <span className="muted small">local · no sign-in needed</span>;
  if (me.login) {
    return (
      <span className="account">
        <img className="avatar" src={`https://github.com/${me.login}.png?size=48`} alt="" width="24" height="24" />
        <span className="account-name">{me.login}</span>
        <button className="btn btn-sm" onClick={signOut}>Sign out</button>
      </span>
    );
  }
  if (!me.available) return <span className="muted small">Sign-in isn't set up here</span>;
  return (
    <a className="btn btn-sm btn-github" href={SIGN_IN_URL}>
      <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z" /></svg>
      Sign in with GitHub
    </a>
  );
}

export default function TopBar({ me, live, crumbs = [] }) {
  return (
    <header className="topbar">
      <a className="brand" href="/">
        <svg className="brand-mark" width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
          <path d="M16 3 L29 11 L29 21 L16 29 L3 21 L3 11 Z" fill="var(--brand)" />
          <path d="M9 21 L9 12 L16 16.5 L23 12 L23 21" fill="none" stroke="#fff" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />
        </svg>
        <span className="brand-name">MaC</span>
      </a>
      <nav className="crumbs" aria-label="Breadcrumb">
        {crumbs.map((c, i) => (
          <span key={i} className="crumb">{i > 0 && <span className="crumb-sep">/</span>}{c}</span>
        ))}
      </nav>
      <span className="spacer" />
      <span className={`live live-${live}`} title={live === "on" ? "Live updates connected" : live === "retry" ? "Reconnecting to the live stream" : "No run is being followed"}>
        <span className="live-dot" />{live === "on" ? "Live" : live === "retry" ? "Reconnecting…" : "Idle"}
      </span>
      <Account me={me} />
    </header>
  );
}
