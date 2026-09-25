import type { IncomingMessage, ServerResponse } from "node:http";
import { createReadStream, existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, extname, normalize, resolve } from "node:path";
import { ROOT, fileToUrl, readRaw, send, json } from "./lib.ts";
import { noteSelfWrite } from "./files.ts";

// PUT write-back is scoped to text artifacts so the endpoint can't drop binaries
// or executable shims into the tree.
const WRITABLE_EXTS = new Set([".md", ".json", ".txt"]);

const MIME: Record<string, string> = {
	".mp4": "video/mp4",
	".webm": "video/webm",
	".mov": "video/quicktime",
	".wav": "audio/wav",
	".mp3": "audio/mpeg",
	".m4a": "audio/mp4",
	".jpg": "image/jpeg",
	".jpeg": "image/jpeg",
	".png": "image/png",
	".gif": "image/gif",
	".webp": "image/webp",
	".json": "application/json",
	".md": "text/markdown; charset=utf-8",
	".txt": "text/plain; charset=utf-8",
	".jsonl": "application/x-ndjson",
	".log": "text/plain; charset=utf-8",
};

// Tail assets_progress.jsonl: catch up on lines already written, then poll for
// appends (fs.watch is unreliable for appends on Windows).
export function streamAssets(req: IncomingMessage, res: ServerResponse, sessionId: string) {
	const progressPath = resolve(ROOT, sessionId, "assets_progress.jsonl");
	if (!progressPath.startsWith(ROOT)) return send(res, 403, "Forbidden");
	res.writeHead(200, {
		"Content-Type": "text/event-stream",
		"Cache-Control": "no-cache",
		Connection: "keep-alive",
		"X-Accel-Buffering": "no",
	});
	res.write(`retry: 2000\n\n`);
	let emitted = 0;
	const flush = () => {
		if (!existsSync(progressPath)) return;
		let text: string;
		try {
			text = readFileSync(progressPath, "utf8");
		} catch {
			return;
		}
		// Only newline-terminated lines are complete; a partial tail waits for the next poll.
		const lines = text.split("\n");
		const complete = lines.slice(0, lines.length - 1);
		for (let i = emitted; i < complete.length; i++) {
			const line = complete[i].trim();
			if (!line) continue;
			let rec: Record<string, unknown>;
			try {
				rec = JSON.parse(line);
			} catch {
				continue;
			}
			const payload = {
				shot_number: rec.shot_number,
				ok: Boolean(rec.ok),
				asset_type: rec.asset_type || "",
				in_point: rec.in_point ?? 0,
				out_point: rec.out_point ?? 0,
				url: rec.ok ? fileToUrl(rec.file, sessionId) : "",
			};
			res.write(`data: ${JSON.stringify(payload)}\n\n`);
		}
		emitted = complete.length;
	};
	flush();
	const poll = setInterval(flush, 1000);
	const ping = setInterval(() => res.write(`: ping\n\n`), 25000);
	const cleanup = () => {
		clearInterval(poll);
		clearInterval(ping);
	};
	req.on("close", cleanup);
	req.on("error", cleanup);
}

// urlPath is relative to ROOT: "/<session-id>/assets/foo.mp4".
export async function serveSessionFile(req: IncomingMessage, res: ServerResponse, urlPath: string) {
	const safe = normalize(urlPath).replace(/^([\\/]|\.\.)+/, "");
	const filePath = resolve(ROOT, safe);
	if (!filePath.startsWith(ROOT)) return send(res, 403, "Forbidden");

	if (req.method === "PUT") {
		const ext = extname(filePath).toLowerCase();
		if (!WRITABLE_EXTS.has(ext)) return send(res, 403, `Not writable: ${ext}`);
		if (!existsSync(dirname(filePath))) return send(res, 404, "Parent directory missing");
		try {
			const body = await readRaw(req);
			writeFileSync(filePath, body);
			noteSelfWrite(filePath, req.headers["x-esta-client"]);
			const st = statSync(filePath);
			return json(res, 200, { ok: true, size: st.size, mtimeMs: st.mtimeMs });
		} catch (e) {
			return send(res, 500, String(e));
		}
	}

	if (!existsSync(filePath)) return send(res, 404, `Not found: ${safe}`);
	const stat = statSync(filePath);
	if (stat.isDirectory()) return send(res, 404, "Directory listing not supported");
	const contentType = MIME[extname(filePath).toLowerCase()] || "application/octet-stream";

	const range = req.headers.range;
	if (range) {
		const m = /^bytes=(\d*)-(\d*)$/.exec(range);
		if (m) {
			const start = m[1] ? parseInt(m[1], 10) : 0;
			const end = m[2] ? parseInt(m[2], 10) : stat.size - 1;
			res.writeHead(206, {
				"Content-Range": `bytes ${start}-${end}/${stat.size}`,
				"Content-Length": end - start + 1,
				"Content-Type": contentType,
			});
			createReadStream(filePath, { start, end }).pipe(res);
			return;
		}
	}
	res.writeHead(200, {
		"Content-Type": contentType,
		"Content-Length": stat.size,
	});
	if (req.method === "HEAD") res.end();
	else createReadStream(filePath).pipe(res);
}
