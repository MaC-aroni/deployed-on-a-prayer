import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The app only calls relative /api/* URLs; in dev, Vite forwards them to the backend.
// BACKEND_URL (set by scripts/dev.sh) picks which one: the live Fly app or your own.
// In prod there's no proxy: FastAPI serves the frontend and /api from one origin.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": { target: env.BACKEND_URL || "http://localhost:8000", changeOrigin: true },
      },
    },
  };
});
