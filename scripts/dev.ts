import { spawn } from "node:child_process";
import { existsSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

// One command for the whole app: the ESTA backend (:8787) and the editor (:3000).
const root = resolve(import.meta.dirname, "..");
const envLocal = resolve(root, "apps", "editor", ".env.local");

// OpenCut validates these at import time; ESTA is local-only and never uses
// auth, the database or Redis, so placeholders satisfy the schema.
if (!existsSync(envLocal)) {
	writeFileSync(
		envLocal,
		[
			"NODE_ENV=development",
			"NEXT_PUBLIC_SITE_URL=http://localhost:3000",
			"NEXT_PUBLIC_MARBLE_API_URL=http://localhost:3000",
			"DATABASE_URL=postgresql://localhost:5432/unused",
			"BETTER_AUTH_SECRET=local-only-not-a-secret",
			"UPSTASH_REDIS_REST_URL=http://localhost:8079",
			"UPSTASH_REDIS_REST_TOKEN=unused",
			"MARBLE_WORKSPACE_KEY=unused",
			"FREESOUND_CLIENT_ID=unused",
			"FREESOUND_API_KEY=unused",
			"",
		].join("\n"),
	);
}

const procs = [
	spawn(process.execPath, ["--watch-path=server", "--watch-preserve-output", "server/index.ts"], { cwd: root, stdio: "inherit" }),
	// bun is a .cmd shim on Windows, which needs a shell; the command is a constant.
	spawn("bun run dev", { cwd: resolve(root, "apps", "editor"), stdio: "inherit", shell: true }),
];

const stop = () => {
	for (const p of procs) if (!p.killed) p.kill();
	process.exit(0);
};
for (const p of procs) p.on("exit", stop);
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
