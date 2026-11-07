import { useEffect, useState } from "react";

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("/api/hello")
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui", padding: 32 }}>
      <h1>deployed-on-a-prayer</h1>
      {error && <p>Backend unreachable: {error}</p>}
      {data && (
        <p>
          {data.message} (env: {data.env})
        </p>
      )}
      {!data && !error && <p>Asking the backend…</p>}
    </main>
  );
}
