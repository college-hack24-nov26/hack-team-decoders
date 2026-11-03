// `defineConfig` must come from vitest/config, not vite, because this file
// carries a `test` block and Vite's own `UserConfigExport` has no `test`
// property — importing from "vite" makes `tsc -b` fail and breaks the
// production build. phase-1 and phase-2 fixed this independently (a
// `/// <reference types="vitest" />` directive vs. this import); keeping both
// would have declared `defineConfig` twice, so the import wins and the
// directive is dropped as redundant.
import react from "@vitejs/plugin-react";
import fs from "fs";
import type http from "http";
import path from "path";
import type { ViteDevServer } from "vite";
import { defineConfig } from "vitest/config";

const landingDir = path.resolve(__dirname, "./landing");

/** Mime types for landing page static assets. */
const MIME: Record<string, string> = {
  ".html": "text/html",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".mp4": "video/mp4",
  ".js": "application/javascript",
  ".json": "application/json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
};

/**
 * Vite plugin that serves the landing page during local dev.
 * Mirrors production: `/` → landing index.html, root-relative assets.
 * Supports HTTP Range requests for video seeking.
 */
function landingPagePlugin() {
  return {
    name: "serve-landing-page",
    configureServer(server: ViteDevServer) {
      server.middlewares.use(
        (req: http.IncomingMessage, res: http.ServerResponse, next: () => void) => {
          const url: string = ((req as { url?: string }).url ?? "").split("?")[0];

          // Don't intercept /kiosk/* or /api/* or /@* (Vite internals)
          if (
            url.startsWith("/kiosk") ||
            url.startsWith("/api") ||
            url.startsWith("/@") ||
            url.startsWith("/node_modules") ||
            url.startsWith("/src")
          ) {
            return next();
          }

          // Serve landing page at root
          if (url === "/" || url === "/index.html") {
            const file = path.join(landingDir, "index.html");
            if (fs.existsSync(file)) {
              res.setHeader("Content-Type", "text/html");
              res.end(fs.readFileSync(file, "utf-8"));
              return;
            }
          }

          // Serve landing page static assets (styles.css, logo.svg, e_scroll.mp4, etc.)
          const cleanUrl = url.startsWith("/") ? url.slice(1) : url;
          if (cleanUrl) {
            // Try the file directly in landing dir, then in assets/ subfolder
            let file = path.join(landingDir, cleanUrl);
            if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {
              file = path.join(landingDir, "assets", cleanUrl);
            }
            if (fs.existsSync(file) && fs.statSync(file).isFile()) {
              const ext = path.extname(file).toLowerCase();
              const mime = MIME[ext] || "application/octet-stream";

              // Handle Range requests (required for video seeking)
              if (ext === ".mp4" && req.headers.range) {
                const stat = fs.statSync(file);
                const total = stat.size;
                const range = req.headers.range;
                const parts = range.replace(/bytes=/, "").split("-");
                const start = parseInt(parts[0], 10);
                const end = parts[1] ? parseInt(parts[1], 10) : total - 1;
                const chunkSize = end - start + 1;

                res.writeHead(206, {
                  "Content-Range": `bytes ${start}-${end}/${total}`,
                  "Accept-Ranges": "bytes",
                  "Content-Length": chunkSize,
                  "Content-Type": mime,
                });
                const stream = fs.createReadStream(file, { start, end });
                stream.pipe(res);
                return;
              }

              // Non-range: serve full file, but advertise Accept-Ranges for videos
              if (ext === ".mp4") {
                const stat = fs.statSync(file);
                res.setHeader("Accept-Ranges", "bytes");
                res.setHeader("Content-Length", stat.size);
              }
              res.setHeader("Content-Type", mime);
              res.end(fs.readFileSync(file));
              return;
            }
          }

          next();
        },
      );
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  base: "/kiosk/",
  plugins: [landingPagePlugin(), react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy API calls to the FastAPI backend during local dev
      "/health": "http://localhost:8000",
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.ts",
  },
});
