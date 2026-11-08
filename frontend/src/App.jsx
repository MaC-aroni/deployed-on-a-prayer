import "./styles.css";
import Shell, { EmptyState } from "./components/Shell.jsx";
import Demo from "./pages/Demo.jsx";
import Migration from "./pages/Migration.jsx";
import Migrations from "./pages/Migrations.jsx";
import Runs from "./pages/Runs.jsx";
import Excuses from "./Excuses.jsx";
import { RouterProvider, matchPath, usePath } from "./router.jsx";

const ORG = { label: "MaC-aroni", to: "/" };

function Routes() {
  const path = usePath();
  let m;

  if (path === "/" || path === "/migrations") {
    return (
      <Shell crumbs={[ORG, { label: "Migrations" }]}>
        <Migrations />
      </Shell>
    );
  }
  if ((m = matchPath("/migrations/:name", path))) {
    const initialRun = new URLSearchParams(window.location.search).get("run");
    return (
      <Shell crumbs={[ORG, { label: "Migrations", to: "/migrations" }, { label: m.name }]}>
        <Migration key={m.name} name={m.name} initialRun={initialRun} />
      </Shell>
    );
  }
  if (path === "/runs") {
    return (
      <Shell crumbs={[ORG, { label: "Runs" }]}>
        <Runs />
      </Shell>
    );
  }
  if (path === "/demo") {
    return (
      <Shell crumbs={[ORG, { label: "Pitch demo" }]}>
        <Demo />
      </Shell>
    );
  }
  if (path === "/excuses") {
    return (
      <Shell crumbs={[ORG, { label: "Excuses" }]}>
        <Excuses />
      </Shell>
    );
  }
  return (
    <Shell crumbs={[ORG, { label: "Not found" }]}>
      <EmptyState title="Not found" body="Try Migrations." />
    </Shell>
  );
}

export default function App() {
  return (
    <RouterProvider>
      <Routes />
    </RouterProvider>
  );
}
