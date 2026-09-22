import { existsSync, statSync, watch } from "node:fs";
import { relative, resolve, sep } from "node:path";
import { ROOT } from "./lib.ts";
import { publish } from "./hub.ts";

export type FileEvent = { session: string; path: string; exists: boolean; mtimeMs: number; size: number; by: string | null };

const listeners = new Set<(ev: FileEvent) => void>();
export function onFileChange(fn: (ev: FileEvent) => void) {
	listeners.add(fn);
}

// Writes made through this server carry the writing tab's id, so that tab can
// tell its own save from an external write (terminal, chat, job).
const selfWrites = new Map<string, { by: string; at: number }>();
export function noteSelfWrite(absPath: string, by: unknown) {
	if (typeof by === "string" && by) selfWrites.set(resolve(absPath), { by, at: Date.now() });
}

const pending = new Map<string, NodeJS.Timeout>();
const lastSeen = new Map<string, string>();

function emit(abs: string) {
	const rel = relative(ROOT, abs);
	const parts = rel.split(sep);
	if (parts.length < 2 || parts[0].startsWith(".")) return;
	const session = parts[0];
	const path = parts.slice(1).join("/");
	if (path.includes("__pycache__")) return;
	let exists = false;
	let mtimeMs = 0;
	let size = 0;
	try {
		const st = statSync(abs);
		if (st.isDirectory()) return;
		exists = true;
		mtimeMs = st.mtimeMs;
		size = st.size;
	} catch {
		/* deleted */
	}
	const sig = `${exists}:${mtimeMs}:${size}`;
	if (lastSeen.get(abs) === sig) return;
	lastSeen.set(abs, sig);
	const self = selfWrites.get(abs);
	const by = self && Date.now() - self.at < 3000 ? self.by : null;
	const ev: FileEvent = { session, path, exists, mtimeMs, size, by };
	publish({ ch: "file", session, data: ev });
	for (const fn of listeners) {
		try {
			fn(ev);
		} catch (e) {
			console.error("[files] listener failed", e);
		}
	}
}

export function startWatcher() {
	if (!existsSync(ROOT)) return;
	watch(ROOT, { recursive: true }, (_event, filename) => {
		if (!filename) return;
		const abs = resolve(ROOT, filename.toString());
		clearTimeout(pending.get(abs));
		pending.set(
			abs,
			setTimeout(() => {
				pending.delete(abs);
				emit(abs);
			}, 150),
		);
	});
}
