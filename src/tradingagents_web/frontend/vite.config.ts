import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// ADR-002/003, INV-WEB-013: the launcher selects only a loopback proxy port.
const backendPort = Number(process.env.TRADINGAGENTS_WEB_BACKEND_PORT ?? 8000);
if (!Number.isInteger(backendPort) || backendPort < 1 || backendPort > 65535) {
  throw new Error("TRADINGAGENTS_WEB_BACKEND_PORT must be between 1 and 65535");
}

export default defineConfig({
  clearScreen: false,
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": `http://127.0.0.1:${backendPort}`,
    },
  },
  build: {
    outDir: "../static",
    emptyOutDir: true,
  },
});
