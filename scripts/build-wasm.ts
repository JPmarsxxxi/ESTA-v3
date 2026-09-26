import { spawnSync } from "node:child_process";
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

// Rebuilds OpenCut's wasm (compositor, effects, masks) from rust/ into
// packages/opencut-wasm, which is committed: running ESTA needs no Rust
// toolchain, only changing rust/ does (rustup target wasm32-unknown-unknown,
// cargo install wasm-pack).
const root = resolve(import.meta.dirname, "..");
const out = resolve(root, "packages", "opencut-wasm");
const args = ["build", "rust/wasm", "--target", "bundler", "--out-dir", out, ...process.argv.slice(2)];
const r = spawnSync("wasm-pack", args, { cwd: root, stdio: "inherit", shell: process.platform === "win32" });
if (r.status !== 0) process.exit(r.status ?? 1);
// wasm-pack ignores its own output; this package is meant to be committed.
rmSync(resolve(out, ".gitignore"), { force: true });
const pkgPath = resolve(out, "package.json");
const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
pkg.version = `${pkg.version.split("-")[0]}-esta`;
writeFileSync(pkgPath, `${JSON.stringify(pkg, null, 2)}\n`);
