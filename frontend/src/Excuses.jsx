import { useEffect, useState } from "react";

export default function Excuses() {
  const [excuse, setExcuse] = useState(null);
  const [error, setError] = useState(null);

  function next() {
    fetch("/api/excuse")
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data) => setExcuse(data.excuse))
      .catch((err) => setError(err.message));
  }

  useEffect(next, []);

  return (
    <>
      <h1>Official excuse generator</h1>
      <p>For when the demo is in five minutes and nothing works.</p>
      <blockquote style={{ fontSize: 24, margin: "32px 0", minHeight: 96 }}>
        {error ? `Even the excuses are down (${error}). That's the excuse.` : (excuse ?? "Thinking of one…")}
      </blockquote>
      <button onClick={next} style={{ fontSize: 16, padding: "8px 16px" }}>
        I need a better one
      </button>
    </>
  );
}
