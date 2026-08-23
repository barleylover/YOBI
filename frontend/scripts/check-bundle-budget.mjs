import { readdir, readFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const distDir = new URL("../dist/", import.meta.url);
const assetDir = new URL("assets/", distDir);
const kib = 1024;

function byteBudget(name, fallback) {
  const value = Number(process.env[name] || fallback);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`BUNDLE_BUDGET_INVALID:${name}`);
  }
  return value;
}

const entryBudget = byteBudget("YOBI_ENTRY_JS_BUDGET_BYTES", 300 * kib);
const chunkBudget = byteBudget("YOBI_JS_CHUNK_BUDGET_BYTES", 300 * kib);

const indexHtml = await readFile(new URL("index.html", distDir), "utf8");
const entryMatch = indexHtml.match(/<script[^>]+type="module"[^>]+src="([^"]+\.js)"/);
if (!entryMatch) {
  throw new Error("BUNDLE_BUDGET_ENTRY_NOT_FOUND");
}

const files = (await readdir(assetDir)).filter((file) => file.endsWith(".js"));
const sizes = new Map();
for (const file of files) {
  sizes.set(file, (await stat(join(fileURLToPath(assetDir), file))).size);
}

const entryFile = entryMatch[1].split("/").at(-1);
const entrySize = entryFile ? sizes.get(entryFile) : undefined;
if (entrySize === undefined) {
  throw new Error(`BUNDLE_BUDGET_ENTRY_MISSING:${entryFile ?? "unknown"}`);
}

const failures = [];
if (entrySize > entryBudget) {
  failures.push(`entry ${entryFile} is ${entrySize} bytes (budget ${entryBudget})`);
}
for (const [file, size] of sizes) {
  if (size > chunkBudget) {
    failures.push(`chunk ${file} is ${size} bytes (budget ${chunkBudget})`);
  }
}

if (failures.length > 0) {
  throw new Error(`BUNDLE_BUDGET_EXCEEDED\n${failures.join("\n")}`);
}

const largest = [...sizes.entries()].sort((left, right) => right[1] - left[1])[0];
console.log(
  `Bundle budget passed: entry ${(entrySize / kib).toFixed(1)} KiB; `
    + `largest chunk ${largest[0]} ${(largest[1] / kib).toFixed(1)} KiB.`,
);
