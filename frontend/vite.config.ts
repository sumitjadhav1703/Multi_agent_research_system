import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

const proxy = {
  "/api": {
    target: "http://127.0.0.1:8000",
    changeOrigin: true,
  },
};

function portfolioLandingDev(): Plugin {
  const landingRoot = join(import.meta.dirname, "landing");
  const mime: Record<string, string> = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
  };

  return {
    name: "portfolio-landing-dev",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url?.split("?")[0] ?? "";
        if (url.startsWith("/app") || url.startsWith("/@") || url.startsWith("/src") || url.startsWith("/node_modules")) {
          next();
          return;
        }
        const rel =
          url === "/" || url === ""
            ? "index.html"
            : url.replace(/^\//, "");
        const filePath = join(landingRoot, rel);
        if (!filePath.startsWith(landingRoot) || !existsSync(filePath)) {
          next();
          return;
        }
        const ext = filePath.slice(filePath.lastIndexOf("."));
        res.setHeader("Content-Type", mime[ext] ?? "application/octet-stream");
        res.end(readFileSync(filePath));
      });
    },
  };
}

export default defineConfig({
  base: "/app/",
  plugins: [portfolioLandingDev(), react(), tailwindcss()],
  build: {
    outDir: "dist/app",
    emptyOutDir: true,
  },
  server: { port: 5173, proxy },
  preview: { proxy },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: false,
  },
});
