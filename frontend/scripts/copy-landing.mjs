import { cpSync, mkdirSync, existsSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const landing = join(root, "landing");
const dist = join(root, "dist");
const publicDir = join(root, "public");

if (!existsSync(landing)) {
  console.error("landing/ is missing");
  process.exit(1);
}

mkdirSync(dist, { recursive: true });

for (const name of ["index.html", "styles.css", "main.js"]) {
  const from = join(landing, name);
  const to = join(dist, name);
  if (!existsSync(from)) {
    console.error(`missing ${from}`);
    process.exit(1);
  }
  if (existsSync(to)) rmSync(to, { recursive: true, force: true });
  cpSync(from, to, { recursive: true });
}

const favicon = join(publicDir, "favicon.svg");
if (existsSync(favicon)) {
  cpSync(favicon, join(dist, "favicon.svg"));
}

console.log("Copied portfolio landing into dist/");
