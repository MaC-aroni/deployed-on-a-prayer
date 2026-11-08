import Excuses from "./Excuses.jsx";
import Home from "./Home.jsx";
import Console from "./mac/Console.jsx";

// The MaC console is the app. The original placeholder pages stay at their own paths.
const PAGES = { "/hello": Home, "/excuses": Excuses };

export default function App() {
  const Page = PAGES[window.location.pathname];
  if (!Page) return <Console />;

  return (
    <main style={{ fontFamily: "system-ui", padding: 32, maxWidth: 640, margin: "0 auto" }}>
      <nav style={{ display: "flex", gap: 16, marginBottom: 24 }}>
        <a href="/">MaC console</a>
        <a href="/hello">Hello</a>
        <a href="/excuses">Excuse generator</a>
      </nav>
      <Page />
    </main>
  );
}
