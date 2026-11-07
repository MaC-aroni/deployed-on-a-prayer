import Excuses from "./Excuses.jsx";
import Home from "./Home.jsx";

const PAGES = { "/": Home, "/excuses": Excuses };

export default function App() {
  const Page = PAGES[window.location.pathname] ?? Home;

  return (
    <main style={{ fontFamily: "system-ui", padding: 32, maxWidth: 640, margin: "0 auto" }}>
      <nav style={{ display: "flex", gap: 16, marginBottom: 24 }}>
        <a href="/">Home</a>
        <a href="/excuses">Excuse generator</a>
      </nav>
      <Page />
    </main>
  );
}
