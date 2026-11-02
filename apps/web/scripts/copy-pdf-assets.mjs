import { cpSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const source = path.dirname(require.resolve("pdfjs-dist/package.json"));
const target = fileURLToPath(new URL("../public/pdf-assets/", import.meta.url));
mkdirSync(target, { recursive: true });
cpSync(
  path.join(source, "build/pdf.worker.min.mjs"),
  path.join(target, "pdf.worker.min.mjs"),
);
for (const name of ["cmaps", "standard_fonts"])
  cpSync(path.join(source, name), path.join(target, name), { recursive: true });
