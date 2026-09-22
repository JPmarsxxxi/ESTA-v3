import type { IncomingMessage, ServerResponse } from "node:http";

// One SSE connection per tab carries every channel (cmd, job, file, pipeline,
// chat). Chrome allows ~6 connections per host; separate streams per panel
// starved ordinary requests in v2.
type Client = { res: ServerResponse; session: string | null; chats: Set<string> };

const clients = new Set<Client>();

export type HubEvent = { ch: string; session?: string; chat?: string; data: unknown };

export function publish(ev: HubEvent) {
	const frame = `data: ${JSON.stringify(ev)}\n\n`;
	for (const c of clients) {
		if (ev.session && c.session !== ev.session) continue;
		if (ev.chat && !c.chats.has(ev.chat)) continue;
		try {
			c.res.write(frame);
		} catch {
			clients.delete(c);
		}
	}
}

export function subscribe(req: IncomingMessage, res: ServerResponse, query: URLSearchParams) {
	res.writeHead(200, {
		"Content-Type": "text/event-stream",
		"Cache-Control": "no-cache, no-transform",
		Connection: "keep-alive",
		"X-Accel-Buffering": "no",
	});
	res.write(`retry: 2000\n\n`);
	const client: Client = {
		res,
		session: query.get("session"),
		chats: new Set(query.getAll("chat").filter(Boolean)),
	};
	clients.add(client);
	res.write(`data: ${JSON.stringify({ ch: "hello", data: { session: client.session } })}\n\n`);
	const ping = setInterval(() => {
		try {
			res.write(`: ping\n\n`);
		} catch {
			/* dropped on next publish */
		}
	}, 20000);
	req.on("close", () => {
		clearInterval(ping);
		clients.delete(client);
	});
}

export function hubSize() {
	return clients.size;
}
