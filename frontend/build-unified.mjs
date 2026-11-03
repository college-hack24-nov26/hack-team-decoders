/**
 * Unified build script — produces a single `dist/` directory containing
 * the landing page at root and the React SPA under `kiosk/`.
 *
 * Output structure:
 *   dist/
 *     index.html       ← landing page
 *     styles.css        ← landing CSS
 *     e_scroll.mp4      ← landing video
 *     logo.svg          ← shared logo
 *     kiosk/            ← React SPA (Vite build output)
 *       index.html
 *       assets/...
 *     _redirects        ← SPA fallback rules
 */

import { execSync } from "child_process";
import { cpSync, mkdirSync, rmSync, existsSync, writeFileSync, copyFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FRONTEND = __dirname;
const OUT = resolve(FRONTEND, "dist");

// Landing page files are bundled in frontend/landing/
const LANDING = resolve(FRONTEND, "landing");

if (!existsSync(resolve(LANDING, "index.html"))) {
  console.error("❌ Landing page files not found at frontend/landing/");
  console.error("   Expected: landing/index.html, landing/styles.css, landing/e_scroll.mp4, landing/logo.svg");
  process.exit(1);
}

// 1. Build React SPA
console.log("🔨 Building React SPA...");
execSync("npm run build:spa", { cwd: FRONTEND, stdio: "inherit" });

// SPA build outputs to dist/ — move it aside, then restructure
const TEMP_SPA = resolve(FRONTEND, ".spa-build-temp");
if (existsSync(TEMP_SPA)) rmSync(TEMP_SPA, { recursive: true });
cpSync(OUT, TEMP_SPA, { recursive: true });
rmSync(OUT, { recursive: true });
mkdirSync(OUT, { recursive: true });

// 2. Copy SPA output to dist/kiosk/
console.log("📦 Copying SPA → dist/kiosk/...");
cpSync(TEMP_SPA, resolve(OUT, "kiosk"), { recursive: true });
rmSync(TEMP_SPA, { recursive: true });

// 3. Copy landing page files to dist/ root
console.log("📦 Copying landing page → dist/...");
copyFileSync(resolve(LANDING, "index.html"), resolve(OUT, "index.html"));
copyFileSync(resolve(LANDING, "styles.css"), resolve(OUT, "styles.css"));

if (existsSync(resolve(LANDING, "e_scroll.mp4"))) {
  copyFileSync(resolve(LANDING, "e_scroll.mp4"), resolve(OUT, "e_scroll.mp4"));
}
if (existsSync(resolve(LANDING, "logo.svg"))) {
  copyFileSync(resolve(LANDING, "logo.svg"), resolve(OUT, "logo.svg"));
}

// 4. Create _redirects for Render SPA routing
writeFileSync(resolve(OUT, "_redirects"), "/kiosk/* /kiosk/index.html 200\n");

console.log("");
console.log("✅ Unified build complete → dist/");
console.log("   /           → Landing page");
console.log("   /kiosk/     → React SPA");
