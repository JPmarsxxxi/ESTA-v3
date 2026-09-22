import type { IncomingMessage, ServerResponse } from "node:http";
import { json, readRaw, send } from "./lib.ts";
import { hubSize, publish } from "./hub.ts";

// Live-edit channel (ESTA -> OpenCut), ported from v2 asset-server.mjs. The MCP
// server POSTs {cmd,...} to /_cmd; every open editor receives it over SSE (the
// legacy /_cmd_stream or the multiplexed /_events "cmd" channel).
const cmdClients = new Set<ServerResponse>();

let latestState: Record<string, unknown> = { tracks: {}, note: "no editor has pushed state yet" };
let statePushedAt = 0;
const STALE_MS = 5000;

// Liveness = the editor heartbeat'd within STALE_MS, so zombie tabs never count.
function isEditorLive() {
	return statePushedAt > 0 && Date.now() - statePushedAt < STALE_MS;
}

async function postJsonInto(req: IncomingMessage, res: ServerResponse, apply: (obj: Record<string, unknown>) => void) {
	try {
		const raw = (await readRaw(req)).toString("utf8");
		apply(JSON.parse(raw || "{}"));
		json(res, 200, { ok: true });
	} catch (e) {
		send(res, 400, `bad JSON: ${e}`);
	}
}

export function handleState(req: IncomingMessage, res: ServerResponse) {
	if (req.method === "GET") {
		const age = statePushedAt ? Date.now() - statePushedAt : null;
		return json(res, 200, {
			...latestState,
			_pushed_at: statePushedAt || null,
			_age_ms: age,
			_stale: age === null || age > STALE_MS,
		});
	}
	return postJsonInto(req, res, (obj) => {
		latestState = obj;
		statePushedAt = Date.now();
	});
}

const acks = new Map<string, unknown>();
const frames = new Map<string, unknown>();

function bounded(map: Map<string, unknown>, max: number) {
	if (map.size > max) map.delete(map.keys().next().value as string);
}

export function handleAck(req: IncomingMessage, res: ServerResponse, query: URLSearchParams) {
	if (req.method === "GET") {
		const reqId = query.get("reqId");
		return json(res, 200, (reqId && acks.get(reqId)) || { pending: true });
	}
	return postJsonInto(req, res, (ack) => {
		if (!ack.reqId) return;
		acks.set(String(ack.reqId), { ...ack, at: Date.now() });
		bounded(acks, 100);
	});
}

export function handleFrame(req: IncomingMessage, res: ServerResponse, query: URLSearchParams) {
	if (req.method === "GET") {
		const reqId = query.get("reqId");
		return json(res, 200, (reqId && frames.get(reqId)) || { pending: true });
	}
	return postJsonInto(req, res, (f) => {
		if (!f.reqId) return;
		frames.set(String(f.reqId), { ...f, at: Date.now() });
		bounded(frames, 12);
	});
}

function broadcastCmd(obj: unknown) {
	const frame = `data: ${JSON.stringify(obj)}\n\n`;
	for (const client of cmdClients) {
		try {
			client.write(frame);
		} catch {
			cmdClients.delete(client);
		}
	}
	publish({ ch: "cmd", data: obj });
	return cmdClients.size + hubSize();
}

export function streamCmds(req: IncomingMessage, res: ServerResponse) {
	res.writeHead(200, {
		"Content-Type": "text/event-stream",
		"Cache-Control": "no-cache",
		Connection: "keep-alive",
	});
	res.write(`: connected\n\n`);
	cmdClients.add(res);
	const ping = setInterval(() => {
		try {
			res.write(`: ping\n\n`);
		} catch {
			/* dropped on next broadcast */
		}
	}, 25000);
	req.on("close", () => {
		clearInterval(ping);
		cmdClients.delete(res);
	});
}

export function injectCmd(req: IncomingMessage, res: ServerResponse) {
	readRaw(req)
		.then((buf) => {
			const obj = JSON.parse(buf.toString("utf8") || "{}");
			const n = broadcastCmd(obj);
			// `delivered` counts raw connections (can include zombies); MCP tools gate on `live`.
			json(res, 200, { ok: true, delivered: n, live: isEditorLive() });
		})
		.catch((e) => send(res, 400, `bad command JSON: ${e}`));
}
