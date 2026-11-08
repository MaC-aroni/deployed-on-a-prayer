import "./styles.css";
import Shell, { EmptyState } from "./components/Shell.jsx";
import Approvals from "./pages/Approvals.jsx";
import Migration from "./pages/Migration.jsx";
import Migrations from "./pages/Migrations.jsx";
import Excuses from "./Excuses.jsx";
import { RouterProvider, matchPath, usePath } from "./router.jsx";

const PROJECT = [
  { label: "MaC-aroni", to: "/" },
  { label: "claims-adjudication", to: "/" },
];

function Routes() {
  const path = usePath();
  let m;

  if (path === "/" || path === "/migrations") {
    return (
      <Shell crumbs={[...PROJECT, { label: "Migrations" }]}>
        <Migrations />
      </Shell>
    );
  }
  if ((m = matchPath("/migrations/:id", path))) {
    return (
      <Shell crumbs={[...PROJECT, { label: "Migrations", to: "/migrations" }, { label: `#${m.id}` }]}>
        <Migration id={m.id} />
      </Shell>
    );
  }
  if (path === "/approvals") {
    return (
      <Shell crumbs={[...PROJECT, { label: "Approvals" }]}>
        <Approvals />
      </Shell>
    );
  }
  if (path === "/excuses") {
    return (
      <Shell crumbs={[...PROJECT, { label: "Excuses" }]}>
        <Excuses />
      </Shell>
    );
  }
  const label = path === "/knowledge" ? "Knowledge graph" : path === "/runs" ? "Runner" : "Not found";
  return (
    <Shell crumbs={[...PROJECT, { label }]}>
      <EmptyState title={label} body="Not in the first mock. The pipeline view at Migrations → #142 is the demo." />
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
