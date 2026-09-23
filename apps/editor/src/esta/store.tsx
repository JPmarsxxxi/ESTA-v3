"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useState, type ReactNode } from "react";
import { api, post, type FileEvent, type Job, type PipelineState } from "./api";
import { connectEvents, useChannel } from "./events";

// Chat transcript, rebuilt from the headless session's stream-json events. It
// lives here (not in the chat panel) so switching workspaces keeps it.
export type ChatItem =
	| { kind: "user"; text: string }
	| { kind: "assistant"; text: string; streaming: boolean }
	| { kind: "tool"; name: string; input: string }
	| { kind: "result"; cost: number | null; error: boolean }
	| { kind: "system"; text: string };

type ChatState = { items: ChatItem[]; alive: boolean; busy: boolean };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type StreamEvent = Record<string, any>;

function chatReducer({ state, ev }: { state: ChatState; ev: StreamEvent }): ChatState {
	const items = [...state.items];
	const last = items[items.length - 1];
	switch (ev.type) {
		case "__reset":
			return { items: [], alive: false, busy: false };
		case "__alive":
			return { ...state, alive: ev.alive };
		case "connected":
			return { ...state, alive: true };
		case "user": {
			// Replayed user events also carry skill bodies and tool results; the
			// turns this UI sent are the ones tagged with the session prefix.
			const text: string = (ev.message?.content ?? []).filter((c: StreamEvent) => c.type === "text").map((c: StreamEvent) => c.text).join("\n");
			const m = /^\[ESTA session:[^\]]*\]\n/.exec(text);
			if (!m) return state;
			return { ...state, busy: true, items: [...items, { kind: "user", text: text.slice(m[0].length) }] };
		}
		case "stream_event": {
			const d = ev.event?.delta;
			if (ev.event?.type !== "content_block_delta" || d?.type !== "text_delta") return state;
			if (last?.kind === "assistant" && last.streaming) items[items.length - 1] = { ...last, text: last.text + d.text };
			else items.push({ kind: "assistant", text: d.text, streaming: true });
			return { ...state, items };
		}
		case "assistant": {
			if (last?.kind === "assistant" && last.streaming) items.pop();
			for (const c of ev.message?.content ?? []) {
				if (c.type === "text" && c.text) items.push({ kind: "assistant", text: c.text, streaming: false });
				if (c.type === "tool_use") items.push({ kind: "tool", name: c.name, input: JSON.stringify(c.input).slice(0, 400) });
			}
			return { ...state, items };
		}
		case "result":
			return { ...state, busy: false, items: [...items, { kind: "result", cost: ev.total_cost_usd ?? null, error: Boolean(ev.is_error) }] };
		case "exit":
			return { ...state, alive: false, busy: false, items: [...items, { kind: "system", text: `Claude session ended (exit ${ev.code ?? ev.signal ?? "?"}).` }] };
		case "bridge_error":
			return { ...state, items: [...items, { kind: "system", text: String(ev.text) }] };
		default:
			return state;
	}
}

type Ctx = {
	session: string;
	stage: string;
	setStage: (id: string) => void;
	pipeline: PipelineState | null;
	pipelineError: string | null;
	refresh: () => void;
	jobs: Job[];
	logs: Record<string, string>;
	appendLog: (args: { id: string; text: string; replace?: boolean }) => void;
	lastFile: FileEvent | null;
	chat: ChatState;
	chatId: string | null;
	selectedShot: number | null;
	selectShot: (n: number | null) => void;
	sendChat: (text: string) => Promise<void>;
	restartChat: () => Promise<void>;
	interruptChat: () => Promise<void>;
};

const WorkspaceContext = createContext<Ctx | null>(null);

export function useWorkspace() {
	const ctx = useContext(WorkspaceContext);
	if (!ctx) throw new Error("useWorkspace outside WorkspaceProvider");
	return ctx;
}

const chatKey = (session: string) => `esta.chat.${session}`;

function readStorage(k: string) {
	try {
		return localStorage.getItem(k);
	} catch {
		return null;
	}
}

function writeStorage({ key, value }: { key: string; value: string | null }) {
	try {
		if (value === null) localStorage.removeItem(key);
		else localStorage.setItem(key, value);
	} catch {
		/* storage unavailable: chat just won't resume across reloads */
	}
}

export function WorkspaceProvider({ session, children }: { session: string; children: ReactNode }) {
	const [pipeline, setPipeline] = useState<PipelineState | null>(null);
	const [pipelineError, setPipelineError] = useState<string | null>(null);
	const [chosenStage, setChosenStage] = useState<string>("");
	const [jobs, setJobs] = useState<Job[]>([]);
	const [logs, setLogs] = useState<Record<string, string>>({});
	const [lastFile, setLastFile] = useState<FileEvent | null>(null);
	const [chatId, setChatId] = useState<string | null>(null);
	// One selected shot across planner, picker and timeline.
	const [selectedShot, selectShot] = useState<number | null>(null);
	const [chat, dispatch] = useReducer((state: ChatState, ev: StreamEvent) => chatReducer({ state, ev }), { items: [], alive: false, busy: false });

	const refresh = useCallback(() => {
		api<PipelineState>(`/_pipeline/${encodeURIComponent(session)}`)
			.then((p) => {
				setPipeline(p);
				setPipelineError(null);
			})
			.catch((e) => setPipelineError(e instanceof Error ? e.message : String(e)));
		api<{ jobs: Job[] }>(`/_jobs?session=${encodeURIComponent(session)}`).then((d) => setJobs(d.jobs)).catch(() => {});
	}, [session]);

	useEffect(refresh, [refresh]);

	// Until the user picks one: the last stage they had open, else the conductor's next.
	const stage = useMemo(() => {
		if (chosenStage) return chosenStage;
		if (!pipeline) return "";
		const stored = readStorage(`esta.stage.${session}`);
		if (stored && pipeline.stages.some((s) => s.id === stored)) return stored;
		return (pipeline.stages.find((s) => s.isNext) ?? pipeline.stages[0]).id;
	}, [chosenStage, pipeline, session]);

	const setStage = useCallback(
		(id: string) => {
			setChosenStage(id);
			writeStorage({ key: `esta.stage.${session}`, value: id });
		},
		[session],
	);

	useEffect(() => {
		void connectEvents({ session, chats: chatId ? [chatId] : [] });
	}, [session, chatId]);

	// A reconnect after a backend restart must not show stale state.
	useChannel({ ch: "hello", fn: refresh });
	useChannel<PipelineState>({ ch: "pipeline", fn: setPipeline });
	useChannel<{ type: string; job?: Job; id?: string; text?: string }>({
		ch: "job",
		fn: (d) => {
			if (d.type === "update" && d.job) {
				const job = d.job;
				setJobs((prev) => [job, ...prev.filter((j) => j.id !== job.id)].sort((a, b) => b.startedAt - a.startedAt));
			}
			if (d.type === "log" && d.id && d.text) {
				const { id, text } = d;
				setLogs((prev) => (id in prev ? { ...prev, [id]: prev[id] + text } : prev));
			}
		},
	});
	useChannel<FileEvent>({ ch: "file", fn: setLastFile });
	useChannel<StreamEvent>({ ch: "chat", fn: (data, ev) => ev.chat === chatId && dispatch(data) });

	// Claude only starts on the first message: an idle workspace shouldn't hold a
	// claude process per open session. A stored id resumes the conversation.
	const ensureChat = useCallback(async () => {
		if (chatId && chat.alive) return chatId;
		const requested = chatId ?? readStorage(chatKey(session));
		let { chat: id } = await post<{ chat: string }>({ path: "/chat/open", body: { chat: requested } });
		await connectEvents({ session, chats: [id] });
		setChatId(id);
		dispatch({ type: "__alive", alive: true });
		if (requested) {
			// A resume of a conversation the CLI no longer has exits at once.
			await new Promise((r) => setTimeout(r, 2500));
			const { alive } = await api<{ alive: boolean }>(`/chat/status?chat=${encodeURIComponent(id)}`);
			if (!alive) {
				id = (await post<{ chat: string }>({ path: "/chat/open", body: { chat: null } })).chat;
				await connectEvents({ session, chats: [id] });
				setChatId(id);
				dispatch({ type: "__alive", alive: true });
			}
		}
		writeStorage({ key: chatKey(session), value: id });
		return id;
	}, [chatId, chat.alive, session]);

	const restartChat = useCallback(async () => {
		if (chatId) await post({ path: "/chat/stop", body: { chat: chatId } }).catch(() => {});
		writeStorage({ key: chatKey(session), value: null });
		setChatId(null);
		dispatch({ type: "__reset" });
	}, [chatId, session]);

	const sendChat = useCallback(
		async (text: string) => {
			const id = await ensureChat();
			// Every turn names the session and stage, so the skills resolve the right folder.
			await post({ path: "/chat/send", body: { chat: id, text: `[ESTA session: sessions/${session} · stage: ${stage}]\n${text}` } });
		},
		[ensureChat, session, stage],
	);

	const interruptChat = useCallback(async () => {
		if (chatId) await post({ path: "/chat/interrupt", body: { chat: chatId } });
	}, [chatId]);

	const appendLog = useCallback(({ id, text, replace }: { id: string; text: string; replace?: boolean }) => {
		setLogs((prev) => ({ ...prev, [id]: replace ? text : (prev[id] ?? "") + text }));
	}, []);

	const value = useMemo<Ctx>(
		() => ({ session, stage, setStage, pipeline, pipelineError, refresh, jobs, logs, appendLog, lastFile, chat, chatId, selectedShot, selectShot, sendChat, restartChat, interruptChat }),
		[session, stage, setStage, pipeline, pipelineError, refresh, jobs, logs, appendLog, lastFile, chat, chatId, selectedShot, sendChat, restartChat, interruptChat],
	);
	return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
