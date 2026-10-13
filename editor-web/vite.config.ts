import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The studio webui. In dev, API/WebSocket traffic proxies to the runtime
// server (`sca edit`, default :7180); `npm run build` emits the
// static bundle the server hosts from simplecadapi/editor/webui.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    port: 5180,
    proxy: {
      "/api": "http://127.0.0.1:7180",
      "/ws": { target: "ws://127.0.0.1:7180", ws: true },
    },
  },
  build: {
    outDir: "../src/simplecadapi/editor/webui",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1600,
  },
});
