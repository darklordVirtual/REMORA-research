// Standalone Vite build for the OT pilot operator console.
//
// The pilot console is a plain SPA — no TanStack Start, no SSR, no Cloudflare
// target — because it is served by the pilot's own console container and talks
// same-origin to the console API. It still lives inside frontend/ so it shares
// the design system (styles.css tokens), the component library and the lint
// setup with the main site. Build with `npm run pilot:build`.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const here = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(here, "src") } },
  build: {
    outDir: "dist-pilot",
    rollupOptions: { input: path.resolve(here, "pilot.html") },
  },
  server: {
    // Local dev against a running pilot: `npm run pilot:dev` proxies the
    // console API of `docker compose -f deploy/ot-pilot/docker-compose.yml`.
    proxy: { "/api": "http://localhost:8081" },
    open: "/pilot.html",
  },
});
