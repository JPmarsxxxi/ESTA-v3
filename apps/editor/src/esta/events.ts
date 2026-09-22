"use client";

import { useEffect, useRef, useState } from "react";
import { BACKEND } from "./api";

// One EventSource per tab carries every channel (pipeline, job, file, chat,
// cmd): Chrome allows ~6 connections per host, and one stream per panel
// starved ordinary requests in v2.
type Meta = { ch: string; session?: string; chat?: string };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Listener<T = any> = (data: T, ev: Meta) => void;

const listeners = new Map<string, Set<Listener>>();
let source: EventSource | null = null;
let key = "";
const status = { connected: false };
const statusListeners = new Set<(connected: boolean) => void>();

function setConnected(connected: boolean) {
	status.connected = connected;
	for (const fn of statusListeners) fn(connected);
}

export function connectEvents({ session, chats }: { session: string | null; chats: string[] }) {
	const next = `${session ?? ""}|${[...chats].sort().join(",")}`;
	if (source && key === next) return;
	source?.close();
	key = next;
	const q = new URLSearchParams();
	if (session) q.set("session", session);
	for (const c of chats) q.append("chat", c);
	source = new EventSource(`${BACKEND}/_events?${q}`);
	source.onopen = () => setConnected(true);
	source.onerror = () => setConnected(false);
	source.onmessage = (e) => {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		let ev: Meta & { data: any };
		try {
			ev = JSON.parse(e.data);
		} catch {
			return;
		}
		for (const fn of listeners.get(ev.ch) ?? []) fn(ev.data, ev);
	};
}

export function onChannel<T>({ ch, fn }: { ch: string; fn: Listener<T> }) {
	if (!listeners.has(ch)) listeners.set(ch, new Set());
	listeners.get(ch)?.add(fn);
	return () => {
		listeners.get(ch)?.delete(fn);
	};
}

export function useChannel<T>({ ch, fn }: { ch: string; fn: Listener<T> }) {
	const ref = useRef(fn);
	useEffect(() => {
		ref.current = fn;
	});
	useEffect(() => onChannel<T>({ ch, fn: (data, ev) => ref.current(data, ev) }), [ch]);
}

export function useEventsConnected() {
	const [connected, setState] = useState(status.connected);
	useEffect(() => {
		statusListeners.add(setState);
		return () => {
			statusListeners.delete(setState);
		};
	}, []);
	return connected;
}
