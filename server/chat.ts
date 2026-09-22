import type { IncomingMessage, ServerResponse } from "node:http";
import { spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import { REPO_ROOT, claudeBin, json, readBody } from "./lib.ts";
import { publish } from "./hub.ts";
import { killTree } from "./jobs.ts";

// Headless Claude Code chat, ported from v2 chat-bridge.mjs. Each chat is one
// persistent `claude --print --input-format stream-json` child in the repo, so
// it loads the same skills, CLAUDE.md and .mcp.json as the terminal.
const PERMISSION_MODE = process.env.CHAT_PERMISSION_MODE || "bypassPermissions";

type Chat = { child: ChildProcess; clients: Set<ServerResponse>; buf: string; alive: boolean };
const chats = new Map<string, Chat>();

function broadcast(id: string, chat: Chat, event: unknown) {
	const payload = `data: ${JSON.stringify(event)}\n\n`;
	for (const res of chat.clients) {
		try {
			res.write(payload);
		} catch {
			/* cleaned up on close */
		}
	}
	publish({ ch: "chat", chat: id, data: event });
}

function spawnChat(id: string, resume: boolean): Chat {
	const args = [
		"--print",
		"--output-format", "stream-json",
		"--input-format", "stream-json",
		"--include-partial-messages",
		"--replay-user-messages",
		"--verbose",
		"--permission-mode", PERMISSION_MODE,
		resume ? "--resume" : "--session-id", id,
	];
	const child = spawn(claudeBin(), args, { cwd: REPO_ROOT, env: process.env, windowsHide: true });
	const chat: Chat = { child, clients: new Set(), buf: "", alive: true };
	chats.set(id, chat);
	child.stdout?.on("data", (chunk: Buffer) => {
		chat.buf += chunk.toString("utf8");
		let nl;
		while ((nl = chat.buf.indexOf("\n")) >= 0) {
			const line = chat.buf.slice(0, nl).trim();
			chat.buf = chat.buf.slice(nl + 1);
			if (!line) continue;
			let event: unknown;
			try {
				event = JSON.parse(line);
			} catch {
				event = { type: "raw", text: line };
			}
			broadcast(id, chat, event);
		}
	});
	child.stderr?.on("data", (chunk: Buffer) => broadcast(id, chat, { type: "stderr", text: chunk.toString("utf8") }));
	child.on("error", (err) => broadcast(id, chat, { type: "bridge_error", text: String(err) }));
	child.on("exit", (code, signal) => {
		chat.alive = false;
		broadcast(id, chat, { type: "exit", code, signal });
		for (const res of chat.clients) {
			try {
				res.end();
			} catch {
				/* ignore */
			}
		}
		chats.delete(id);
	});
	console.log(`[chat] ${id} ${resume ? "resumed" : "started"} (pid ${child.pid})`);
	return chat;
}

// Attach to a live chat, resume a persisted one (id given but no child, e.g.
// after a server restart), or start fresh.
function ensureChat(requested: string | null, resume: boolean) {
	const id = requested || randomUUID();
	return { id, chat: chats.get(id) || spawnChat(id, Boolean(requested) && resume) };
}

export function chatStream(req: IncomingMessage, res: ServerResponse, query: URLSearchParams) {
	const { id, chat } = ensureChat(query.get("session"), true);
	res.writeHead(200, {
		"Content-Type": "text/event-stream",
		"Cache-Control": "no-cache, no-transform",
		Connection: "keep-alive",
		"X-Accel-Buffering": "no",
	});
	res.write(`data: ${JSON.stringify({ type: "connected", session: id })}\n\n`);
	chat.clients.add(res);
	const ping = setInterval(() => {
		try {
			res.write(": ping\n\n");
		} catch {
			/* ignore */
		}
	}, 15000);
	req.on("close", () => {
		clearInterval(ping);
		chat.clients.delete(res);
	});
}

// Multiplexed variant: events flow over /_events?chat=<id>.
export async function chatOpen(req: IncomingMessage, res: ServerResponse) {
	const body = await readBody(req).catch(() => ({}) as Record<string, unknown>);
	const requested = typeof body.chat === "string" && body.chat ? body.chat : null;
	const { id } = ensureChat(requested, body.resume !== false);
	json(res, 200, { ok: true, chat: id });
}

export async function chatSend(req: IncomingMessage, res: ServerResponse) {
	const body = await readBody(req).catch(() => ({}) as Record<string, unknown>);
	const id = String(body.session || body.chat || "");
	const text = body.text;
	if (!id || typeof text !== "string" || !text.trim()) return json(res, 400, { error: "session and non-empty text required" });
	const chat = chats.get(id);
	if (!chat || !chat.alive) return json(res, 404, { error: "no live session — open /chat/stream first" });
	const msg = { type: "user", message: { role: "user", content: [{ type: "text", text }] } };
	chat.child.stdin?.write(JSON.stringify(msg) + "\n");
	json(res, 200, { ok: true });
}

// Graceful interrupt of the current turn (the CLI's ESC); the session survives.
export async function chatInterrupt(req: IncomingMessage, res: ServerResponse) {
	const body = await readBody(req).catch(() => ({}) as Record<string, unknown>);
	const chat = chats.get(String(body.session || body.chat || ""));
	if (!chat || !chat.alive) return json(res, 404, { error: "no live session" });
	const request_id = `int_${randomUUID()}`;
	chat.child.stdin?.write(JSON.stringify({ type: "control_request", request_id, request: { subtype: "interrupt" } }) + "\n");
	json(res, 200, { ok: true, request_id });
}

export async function chatStop(req: IncomingMessage, res: ServerResponse) {
	const body = await readBody(req).catch(() => ({}) as Record<string, unknown>);
	const chat = chats.get(String(body.session || body.chat || ""));
	if (chat?.child.pid) killTree(chat.child.pid);
	json(res, 200, { ok: true });
}

export function chatHealth(res: ServerResponse) {
	json(res, 200, { ok: true, permissionMode: PERMISSION_MODE, sessions: [...chats.keys()], repoRoot: REPO_ROOT });
}

export function chatStatus(res: ServerResponse, query: URLSearchParams) {
	const chat = chats.get(String(query.get("chat")));
	json(res, 200, { alive: Boolean(chat?.alive) });
}

export function stopAllChats() {
	for (const { child } of chats.values()) if (child.pid) killTree(child.pid);
}
