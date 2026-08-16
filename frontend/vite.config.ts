import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI app registers no CORS middleware, so the browser cannot call
// http://localhost:8000 directly from the dev server origin. Proxying /api
// keeps the request same-origin and leaves the backend untouched.
//
// A financial query runs the whole graph (intent -> planner -> retrieval ->
// scoring -> analysis -> reviewer) and has been observed to take 30-150s, so
// the proxy timeouts are raised well above the defaults.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        timeout: 900_000,
        proxyTimeout: 900_000,
      },
      // The evaluation screen's system indicator reads GET /health, which is
      // mounted at the app root rather than under /api.
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // The LLM provider registry the evaluation screen reads is mounted at
      // /admin/llm, outside the /api prefix above.
      "/admin": {
        target: "http://localhost:8000",
        changeOrigin: true,
        timeout: 900_000,
        proxyTimeout: 900_000,
      },
    },
  },
});
