import type { ServerResponse } from "node:http";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { PY_ENV, REPO_ROOT, ROOT, STATE_DIR, estaPython, fileToUrl, json, sessionDir, type Json } from "./lib.ts";

type Media = Json & { url: string };
type Clip = { id: string; mediaId: string; startTime: number; duration: number };
type Pending = { clipId: string; shot: number; track: string; name: string; startTime: number; duration: number; url?: string; mediaType?: string; inPoint?: number; size?: number; mtimeMs?: number };

const fileStat = (url: string) => {
	try {
		const st = statSync(resolve(ROOT, decodeURIComponent(url.replace(/^\/api\/sessions\//, ""))));
		return { size: st.size, mtimeMs: Math.round(st.mtimeMs) };
	} catch {
		return null;
	}
};

// Per-shot asset results, merged as render's _load_asset_shots does:
// assets.json first, then the live assets_progress.jsonl feed, later lines win.
function assetShots(dir: string) {
	const shots: Record<string, Json> = {};
	try {
		Object.assign(shots, (JSON.parse(readFileSync(resolve(dir, "assets.json"), "utf8")) as { shots?: Record<string, Json> }).shots ?? {});
	} catch {}
	const feed = resolve(dir, "assets_progress.jsonl");
	if (existsSync(feed)) {
		for (const line of readFileSync(feed, "utf8").split("\n")) {
			try {
				const r = JSON.parse(line) as Json;
				if (r.shot_number != null) shots[String(r.shot_number)] = r;
			} catch {}
		}
	}
	return shots;
}

// from_openreel.py drops clips with no media yet: the early render pass's
// stream-pending shots. List them so the editor can hold their place, filled
// from the asset feed when a shot has landed since render ran.
function pendingShots(dir: string, session: string, originals: boolean): Pending[] {
	let doc: Json;
	try {
		doc = JSON.parse(readFileSync(resolve(dir, `${session}.openreel.json`), "utf8"));
	} catch {
		return [];
	}
	const project = (doc.project ?? doc) as { mediaLibrary?: { items?: Json[] }; timeline?: { tracks?: { name: string; type: string; clips?: Clip[] }[] } };
	const items = new Map((project.mediaLibrary?.items ?? []).map((m) => [String(m.id), m]));
	const feed = assetShots(dir);
	const out: Pending[] = [];
	for (const track of project.timeline?.tracks ?? []) {
		if (track.type !== "video") continue;
		for (const clip of track.clips ?? []) {
			const media = items.get(clip.mediaId);
			const shot = /^media-shot-(\d+)$/.exec(clip.mediaId);
			if (!media || media.originalUrl || !shot) continue;
			const p: Pending = { clipId: clip.id, shot: Number(shot[1]), track: track.name, name: String(media.name ?? ""), startTime: clip.startTime, duration: clip.duration };
			const asset = feed[shot[1]];
			if (asset?.ok && asset.file) {
				let url = fileToUrl(asset.file, session);
				// Same proxy preference as from_openreel.py.
				const proxy = url.replace("/assets/source_pool/", "/assets/proxies/");
				if (!originals && proxy !== url && fileStat(proxy)) url = proxy;
				const st = fileStat(url);
				if (st) Object.assign(p, { url, mediaType: asset.asset_type === "video" ? "video" : "image", inPoint: Number(asset.in_point) || 0, ...st });
			}
			out.push(p);
		}
	}
	return out;
}

// The editor builds its native project from from_openreel.py's intermediate, so
// the track mapping, proxy choice and caption chunking stay v2's code. Each
// media entry gets the file's size and mtime so the editor only re-downloads
// what changed.
export function opencutImport(res: ServerResponse, session: string, originals: boolean) {
	const dir = sessionDir(session);
	if (!dir) return json(res, 400, { error: "bad session" });
	const py = estaPython();
	if (!py) return json(res, 500, { error: "esta env python not found — set ESTA_PYTHON to its full path and restart the server" });
	const outDir = resolve(STATE_DIR, "opencut");
	mkdirSync(outDir, { recursive: true });
	const out = resolve(outDir, `${session}.${originals ? "originals" : "proxies"}.json`);
	const args = ["tools/opencut/from_openreel.py", "--session", `sessions/${session}`, "--out", out];
	if (originals) args.push("--originals");
	// shell:false: argv never reaches a command interpreter.
	const child = spawn(py, args, { cwd: REPO_ROOT, env: PY_ENV });
	let stdout = "";
	let stderr = "";
	child.stdout.on("data", (d) => (stdout += d));
	child.stderr.on("data", (d) => (stderr += d));
	child.on("error", (e) => json(res, 500, { error: String(e.message || e) }));
	child.on("close", (code) => {
		const line = stdout.trim().split("\n").filter((l) => l.trim().startsWith("{")).pop();
		let summary: Json | null = null;
		try {
			summary = line ? JSON.parse(line) : null;
		} catch {}
		if (code !== 0 || !summary?.ok) {
			const error = typeof summary?.error === "string" ? summary.error : stderr.slice(-500) || `from_openreel exited ${code}`;
			return json(res, /No openreel\.json/.test(error) ? 404 : 500, { error });
		}
		const doc = JSON.parse(readFileSync(out, "utf8")) as Json & { media: Media[] };
		for (const m of doc.media) Object.assign(m, fileStat(m.url) ?? { missing: true });
		json(res, 200, { ...doc, pending: pendingShots(dir, session, originals), originals, summary });
	});
}
