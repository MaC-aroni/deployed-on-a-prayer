import { createContext, useContext, useEffect, useState } from "react";

// Minimal history-based router. Prod serves index.html for every non-/api path
// (see backend/app/main.py), so deep links work without extra config.

const PathContext = createContext("/");

export function RouterProvider({ children }) {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const onChange = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onChange);
    return () => window.removeEventListener("popstate", onChange);
  }, []);
  return <PathContext.Provider value={path}>{children}</PathContext.Provider>;
}

export function usePath() {
  return useContext(PathContext);
}

export function navigate(to) {
  if (to === window.location.pathname) return;
  window.history.pushState({}, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function Link({ to, children, ...rest }) {
  function onClick(e) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    navigate(to);
  }
  return (
    <a href={to} onClick={onClick} {...rest}>
      {children}
    </a>
  );
}

// matchPath("/migrations/:id", "/migrations/142") -> { id: "142" } or null
export function matchPath(pattern, path) {
  const p = pattern.split("/").filter(Boolean);
  const a = path.split("/").filter(Boolean);
  if (p.length !== a.length) return null;
  const params = {};
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(":")) params[p[i].slice(1)] = decodeURIComponent(a[i]);
    else if (p[i] !== a[i]) return null;
  }
  return params;
}
