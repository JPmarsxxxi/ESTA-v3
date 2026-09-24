"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { EditorCore } from "@/core";
import { useKeybindingsStore } from "@/actions/keybindings-store";
import { EditorRuntimeBindings } from "@/components/providers/editor-provider";
import { loadFontAtlas } from "@/fonts/google-fonts";
import { initializeGpuRenderer, isGpuAvailable } from "@/services/renderer/gpu-renderer";
import { storageService } from "@/services/storage/service";
import { ApiError, CLIENT_ID, api, type FileEvent } from "../api";
import { useChannel } from "../events";
import { useWorkspace } from "../store";
import { type EmitProgress, emitSession, projectIdFor } from "./emit";

type Status = "idle" | "loading" | "ready" | "missing" | "error";

export type Built = { originals: boolean; at: number; source: number; summary: Record<string, unknown>; missing: string[] };

type Ctx = {
	projectId: string;
	status: Status;
	error: string | null;
	built: Built | null;
	progress: EmitProgress | null;
	buildError: string | null;
	// Render changed the project while the timeline has edits of its own.
	conflict: boolean;
	open: () => void;
	build: (originals: boolean) => Promise<void>;
	keepMine: () => void;
};

const OpenCutContext = createContext<Ctx | null>(null);

export function useOpenCut() {
	const ctx = useContext(OpenCutContext);
	if (!ctx) throw new Error("useOpenCut outside OpenCutHost");
	return ctx;
}

const builtKey = (session: string) => `esta.opencut.${session}`;

function readBuilt(session: string): Built | null {
	try {
		return JSON.parse(localStorage.getItem(builtKey(session)) || "null");
	} catch {
		return null;
	}
}

// Everything the built project is derived from: render's output, plus the asset
// feed that hydrates its pending shots.
const sourceFiles = (session: string) => new Set([`${session}.openreel.json`, "assets_progress.jsonl", "assets.json"]);

async function sourceMtime(session: string) {
	const { files } = await api<{ files: { path: string; mtimeMs: number }[] }>(`/_files/${encodeURIComponent(session)}/list`);
	const names = sourceFiles(session);
	return Math.max(0, ...files.filter((f) => names.has(f.path)).map((f) => f.mtimeMs));
}

// OpenCut's EditorCore is a singleton, so the workspace hosts one project: the
// session's esta-<id>. It loads the first time an OpenCut panel is shown and
// stays loaded across stage switches; shortcuts only listen on the Edit stage,
// so Delete in the planner can't delete a clip. Once built, the project follows
// render: a new revision rebuilds and reloads it in place, unless the timeline
// has edits of its own, which raises a conflict instead of overwriting them.
export function OpenCutHost({ children }: { children: ReactNode }) {
	const { session, stage } = useWorkspace();
	const projectId = projectIdFor(session);
	const [status, setStatusState] = useState<Status>(() =>
		EditorCore.getInstance().project.getActiveOrNull()?.metadata.id === projectId ? "ready" : "idle",
	);
	const [error, setError] = useState<string | null>(null);
	const [built, setBuilt] = useState<Built | null>(() => readBuilt(session));
	const [progress, setProgress] = useState<EmitProgress | null>(null);
	const [buildError, setBuildError] = useState<string | null>(null);
	const [conflict, setConflict] = useState(false);
	// Every OpenCut panel calls open() in the same commit, and file events can
	// land mid-build; refs make those decisions without waiting for a render.
	const statusRef = useRef<Status | null>(null);
	const builtRef = useRef(built);
	const building = useRef(false);
	const again = useRef(false);
	const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
	const setStatus = useCallback((s: Status) => {
		statusRef.current = s;
		setStatusState(s);
	}, []);
	const { setLoadingProject } = useKeybindingsStore();

	const load = useCallback(async () => {
		const editor = EditorCore.getInstance();
		const playhead = editor.project.getActiveOrNull()?.metadata.id === projectId ? editor.playback.getCurrentTime() : null;
		// Panels unmount while loading: loadProject clears the scenes they read.
		setStatus("loading");
		setLoadingProject(true);
		try {
			// Not built yet is a normal state; OpenCut would log it as an error.
			if (!(await storageService.loadProject({ id: projectId }))) {
				setStatus("missing");
				return;
			}
			await initializeGpuRenderer();
			editor.renderer.setDegraded(!isGpuAvailable());
			await editor.project.loadProject({ id: projectId });
			// Undo history is what "edited since the last build" means below.
			editor.command.clear();
			loadFontAtlas();
			setError(null);
			setStatus("ready");
			// After the panels remount: the timeline resets the playhead as it mounts.
			if (playhead !== null) setTimeout(() => editor.playback.seek({ time: playhead }), 0);
		} catch (e) {
			const msg = e instanceof Error ? e.message : String(e);
			setError(msg);
			setStatus("error");
		} finally {
			setLoadingProject(false);
		}
	}, [projectId, setLoadingProject, setStatus]);

	const build = useCallback(
		async (originals: boolean) => {
			if (building.current) {
				again.current = true;
				return;
			}
			building.current = true;
			const editor = EditorCore.getInstance();
			let mode = originals;
			try {
				do {
					again.current = false;
					setBuildError(null);
					setConflict(false);
					const loaded = editor.project.getActiveOrNull()?.metadata.id === projectId;
					// A pending autosave of the open project would overwrite the fresh build.
					if (loaded) {
						await editor.save.flush();
						editor.save.pause();
					}
					try {
						const source = await sourceMtime(session);
						const r = await emitSession({ session, originals: mode, onProgress: setProgress });
						const next = { originals: r.originals, at: Date.now(), source, summary: r.summary, missing: r.missing };
						builtRef.current = next;
						setBuilt(next);
						try {
							localStorage.setItem(builtKey(session), JSON.stringify(next));
						} catch {
							/* the build record just won't persist */
						}
						if (loaded || (statusRef.current ?? status) !== "idle") await load();
					} catch (e) {
						setBuildError(e instanceof ApiError && e.status === 404 ? "No render output yet: run render first." : e instanceof Error ? e.message : String(e));
					} finally {
						editor.save.resume();
						setProgress(null);
					}
					mode = builtRef.current?.originals ?? mode;
				} while (again.current);
			} finally {
				building.current = false;
			}
		},
		[load, projectId, session, status],
	);

	// Follow render only once the user has built; a first build stays a choice.
	const follow = useCallback(() => {
		const last = builtRef.current;
		if (!last) return;
		const editor = EditorCore.getInstance();
		if (editor.project.getActiveOrNull()?.metadata.id === projectId && editor.command.canUndo()) setConflict(true);
		else void build(last.originals);
	}, [build, projectId]);
	const followRef = useRef(follow);
	useEffect(() => {
		followRef.current = follow;
	});

	useChannel<FileEvent>({
		ch: "file",
		fn: (ev) => {
			if (ev.session !== session || ev.by === CLIENT_ID || !ev.exists || !sourceFiles(session).has(ev.path)) return;
			// Render and the asset fetch write in bursts; rebuild once they settle.
			if (timer.current) clearTimeout(timer.current);
			timer.current = setTimeout(() => followRef.current(), 1500);
		},
	});

	// Revisions written while this workspace wasn't open.
	useEffect(() => {
		const last = builtRef.current;
		if (!last) return;
		sourceMtime(session)
			.then((m) => m > (last.source ?? last.at) && followRef.current())
			.catch(() => {});
	}, [session]);

	useEffect(
		() => () => {
			if (timer.current) clearTimeout(timer.current);
			const editor = EditorCore.getInstance();
			if (editor.project.getActiveOrNull()?.metadata.id === projectId) void editor.save.flush();
		},
		[projectId],
	);

	const open = useCallback(() => {
		if ((statusRef.current ?? status) === "idle") void load();
	}, [load, status]);

	const keepMine = useCallback(() => setConflict(false), []);

	const value = useMemo(
		() => ({ projectId, status, error, built, progress, buildError, conflict, open, build, keepMine }),
		[projectId, status, error, built, progress, buildError, conflict, open, build, keepMine],
	);
	return (
		<OpenCutContext.Provider value={value}>
			{status === "ready" && stage === "edit" && <EditorRuntimeBindings />}
			{children}
		</OpenCutContext.Provider>
	);
}
