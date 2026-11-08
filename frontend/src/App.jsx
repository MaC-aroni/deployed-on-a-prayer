import "./styles.css";
import Shell, { EmptyState } from "./components/Shell.jsx";
import Agents from "./pages/Agents.jsx";
import Chat from "./pages/Chat.jsx";
import Demo from "./pages/Demo.jsx";
import Knowledge from "./pages/Knowledge.jsx";
import Migrate from "./pages/Migrate.jsx";
import Migration from "./pages/Migration.jsx";
import Migrations from "./pages/Migrations.jsx";
import Planning from "./pages/Planning.jsx";
import Runs from "./pages/Runs.jsx";
import Services from "./pages/Services.jsx";
import Excuses from "./Excuses.jsx";
import Home from "./Home.jsx";
import { RouterProvider, matchPath, usePath } from "./router.jsx";

// The MaC console is the app. The starter's placeholder pages stay at /hello and /excuses.
// ob1-can-obi's first console (src/mac/Console.jsx) is superseded by these pages and is not
// routed; see plan.md.

const ORG = { label: "MaC-aroni", to: "/" };

function Routes() {
  const path = usePath();
  let m;

  if (path === "/" || path === "/migrations") {
    return (
      <Shell crumbs={[ORG, { label: "Pipelines" }]}>
        <Migrations />
      </Shell>
    );
  }
  if ((m = matchPath("/migrations/:name", path))) {
    const initialRun = new URLSearchParams(window.location.search).get("run");
    return (
      <Shell crumbs={[ORG, { label: m.name }]}>
        <Migration key={`m:${m.name}`} source={{ kind: "migration", id: m.name }} initialRun={initialRun} />
      </Shell>
    );
  }
  if ((m = matchPath("/plans/:runId", path))) {
    const initialRun = new URLSearchParams(window.location.search).get("run");
    return (
      <Shell crumbs={[ORG, { label: `plan ${m.runId}` }]}>
        <Migration key={`p:${m.runId}`} source={{ kind: "plan", id: m.runId }} initialRun={initialRun} />
      </Shell>
    );
  }
  if (path === "/migrate") {
    return (
      <Shell crumbs={[ORG, { label: "Migration" }]}>
        <Migrate />
      </Shell>
    );
  }
  if ((m = matchPath("/agents/:runId", path))) {
    return (
      <Shell crumbs={[ORG, { label: m.runId === "demo" ? "Agents" : `agents ${m.runId}` }]}>
        <Agents key={m.runId} runId={m.runId} />
      </Shell>
    );
  }
  if ((m = matchPath("/knowledge/:pageId", path))) {
    return (
      <Shell crumbs={[ORG, { label: "Knowledge", to: "/migrate" }, { label: m.pageId }]}>
        <Knowledge key={m.pageId} pageId={m.pageId} />
      </Shell>
    );
  }
  if ((m = matchPath("/migrate/:runId", path))) {
    return (
      <Shell crumbs={[ORG, { label: `planning ${m.runId}` }]}>
        <Planning key={m.runId} runId={m.runId} />
      </Shell>
    );
  }
  if (path === "/chat" || (m = matchPath("/chat/:id", path))) {
    return (
      <Shell crumbs={[ORG, { label: "Chat" }]}>
        <Chat key={m?.id ?? "new"} chatId={m?.id ?? null} />
      </Shell>
    );
  }
  if (path === "/services") {
    return (
      <Shell crumbs={[ORG, { label: "Services" }]}>
        <Services />
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
      <Shell crumbs={[ORG, { label: "Demo" }]}>
        <Demo />
      </Shell>
    );
  }
  if (path === "/hello" || path === "/excuses") {
    const Page = path === "/hello" ? Home : Excuses;
    return (
      <Shell crumbs={[ORG, { label: path === "/hello" ? "Hello" : "Excuses" }]}>
        <Page />
      </Shell>
    );
  }
  return (
    <Shell crumbs={[ORG, { label: "Not found" }]}>
      <EmptyState title="Not found" body="Try Build → Migration, or Pipelines." />
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
