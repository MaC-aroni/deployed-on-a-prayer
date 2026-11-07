import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The app only calls relative /api/* URLs; Vite forwards them to the backend.
// BACKEND_URL in frontend/.env picks which one: the host laptop or your own.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxy = {
    "/api": { target: env.BACKEND_URL || "http://localhost:8000", changeOrigin: true },
  };
  // allowedHosts: teammates open the host's frontend by its Tailscale name.
  return {
    plugins: [react()],
    server: { proxy, allowedHosts: true },
    preview: { proxy, allowedHosts: true },
  };
});
