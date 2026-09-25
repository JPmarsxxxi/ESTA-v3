"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { CLIENT_ID, apiText, sessionFileUrl } from "./api";
import { useWorkspace } from "./store";

// A session file edited in the UI while the terminal, chat or a job may write
// it too. External change + no local edits: reload silently. External change
// + local edits: hold the disk version and ask (never overwrite either way).
export function useSessionDoc<T>({
	path,
	parse,
	serialize,
	debounceMs = 600,
}: {
	path: string;
	parse: (text: string) => T;
	serialize: (value: T) => string;
	debounceMs?: number;
}) {
	const { session, lastFile } = useWorkspace();
	const [value, setValue] = useState<T | null>(null);
	const [missing, setMissing] = useState(false);
	const [saving, setSaving] = useState(false);
	const [conflict, setConflictState] = useState<T | null>(null);
	const baseline = useRef<string | null>(null);
	// While the banner is up nothing autosaves: either choice must stay possible.
	const held = useRef(false);
	const dirty = useRef(false);
	const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
	const setConflict = useCallback((disk: T | null) => {
		held.current = disk !== null;
		if (held.current && timer.current) clearTimeout(timer.current);
		setConflictState(disk);
	}, []);
	const parseRef = useRef(parse);
	const serializeRef = useRef(serialize);
	useEffect(() => {
		parseRef.current = parse;
		serializeRef.current = serialize;
	});

	const fetchDisk = useCallback(
		() =>
			apiText(`/api/sessions/${encodeURIComponent(session)}/${path}`).then(
				(text) => ({ text, parsed: parseRef.current(text) }),
				() => null,
			),
		[session, path],
	);

	useEffect(() => {
		fetchDisk().then((r) => {
			if (!r) return setMissing(true);
			baseline.current = r.text;
			dirty.current = false;
			setMissing(false);
			setValue(r.parsed);
		});
	}, [fetchDisk]);

	useEffect(() => {
		if (!lastFile || lastFile.path !== path || lastFile.by === CLIENT_ID) return;
		fetchDisk().then((r) => {
			if (!r) return;
			if (r.text === baseline.current) return;
			if (dirty.current) return setConflict(r.parsed);
			baseline.current = r.text;
			setMissing(false);
			setValue(r.parsed);
		});
	}, [lastFile, path, fetchDisk, setConflict]);

	const write = useCallback(
		async (next: T) => {
			const text = serializeRef.current(next);
			setSaving(true);
			try {
				const res = await fetch(sessionFileUrl({ session, path }), {
					method: "PUT",
					headers: { "Content-Type": "text/plain", "X-Esta-Client": CLIENT_ID },
					body: text,
				});
				if (!res.ok) throw new Error(await res.text());
				baseline.current = text;
				dirty.current = false;
				setMissing(false);
			} finally {
				setSaving(false);
			}
		},
		[session, path],
	);

	const change = useCallback(
		(next: T) => {
			setValue(next);
			dirty.current = true;
			if (timer.current) clearTimeout(timer.current);
			if (!held.current) timer.current = setTimeout(() => void write(next), debounceMs);
		},
		[write, debounceMs],
	);

	// Keep mine: write the local version over the disk one. Take theirs: adopt disk.
	const resolve = useCallback(
		(keepMine: boolean) => {
			if (keepMine && value !== null) void write(value);
			if (!keepMine && conflict !== null) {
				baseline.current = serializeRef.current(conflict);
				dirty.current = false;
				setValue(conflict);
			}
			setConflict(null);
		},
		[conflict, value, write, setConflict],
	);

	return { value, missing, saving, conflict: conflict !== null, change, resolve };
}

export function ConflictBanner({ what, onResolve }: { what: string; onResolve: (keepMine: boolean) => void }) {
	return (
		<div className="bg-caution/15 border-caution/40 flex flex-wrap items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs">
			<span className="flex-1">{what} changed on disk while you had unsaved edits.</span>
			<Button size="sm" variant="outline" onClick={() => onResolve(true)}>
				Keep mine
			</Button>
			<Button size="sm" variant="outline" onClick={() => onResolve(false)}>
				Take theirs
			</Button>
		</div>
	);
}

// Local session paths stay same-origin (Next rewrites them to the backend);
// remote candidate URLs are used as they are.
export const mediaUrl = (url: string | null | undefined) => url ?? "";
