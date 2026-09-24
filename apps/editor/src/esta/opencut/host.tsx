"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { EditorCore } from "@/core";
import { useKeybindingsStore } from "@/actions/keybindings-store";
import { EditorRuntimeBindings } from "@/components/providers/editor-provider";
import { loadFontAtlas } from "@/fonts/google-fonts";
import { initializeGpuRenderer, isGpuAvailable } from "@/services/renderer/gpu-renderer";
import { useWorkspace } from "../store";
import { type EmitProgress, emitSession, projectIdFor } from "./emit";

type Status = "idle" | "loading" | "ready" | "missing" | "error";

type Ctx = {
	projectId: string;
	status: Status;
	error: string | null;
	open: () => void;
	rebuild: (args: { originals: boolean; onProgress: (p: EmitProgress) => void }) => ReturnType<typeof emitSession>;
};

const OpenCutContext = createContext<Ctx | null>(null);

export function useOpenCut() {
	const ctx = useContext(OpenCutContext);
	if (!ctx) throw new Error("useOpenCut outside OpenCutHost");
	return ctx;
}

// OpenCut's EditorCore is a singleton, so the workspace hosts one project: the
// session's esta-<id>. It loads the first time an OpenCut panel is shown and
// stays loaded across stage switches; shortcuts only listen on the Edit stage,
// so Delete in the planner can't delete a clip.
export function OpenCutHost({ children }: { children: ReactNode }) {
	const { session, stage } = useWorkspace();
	const projectId = projectIdFor(session);
	const [status, setStatusState] = useState<Status>(() =>
		EditorCore.getInstance().project.getActiveOrNull()?.metadata.id === projectId ? "ready" : "idle",
	);
	const [error, setError] = useState<string | null>(null);
	// Every OpenCut panel calls open() in the same commit; the ref makes the
	// first call the only load.
	const statusRef = useRef<Status | null>(null);
	const setStatus = useCallback((s: Status) => {
		statusRef.current = s;
		setStatusState(s);
	}, []);
	const { setLoadingProject } = useKeybindingsStore();

	const load = useCallback(async () => {
		const editor = EditorCore.getInstance();
		setStatus("loading");
		setLoadingProject(true);
		try {
			await initializeGpuRenderer();
			editor.renderer.setDegraded(!isGpuAvailable());
			await editor.project.loadProject({ id: projectId });
			loadFontAtlas();
			setError(null);
			setStatus("ready");
		} catch (e) {
			const msg = e instanceof Error ? e.message : String(e);
			setError(msg);
			setStatus(/not found/.test(msg) ? "missing" : "error");
		} finally {
			setLoadingProject(false);
		}
	}, [projectId, setLoadingProject, setStatus]);

	const open = useCallback(() => {
		if ((statusRef.current ?? status) === "idle") void load();
	}, [load, status]);

	const rebuild = useCallback<Ctx["rebuild"]>(
		async ({ originals, onProgress }) => {
			const editor = EditorCore.getInstance();
			const loaded = editor.project.getActiveOrNull()?.metadata.id === projectId;
			// A pending autosave of the open project would overwrite the fresh build.
			if (loaded) {
				await editor.save.flush();
				editor.save.pause();
			}
			try {
				const result = await emitSession({ session, originals, onProgress });
				if (loaded || (statusRef.current ?? status) !== "idle") await load();
				return result;
			} finally {
				editor.save.resume();
			}
		},
		[load, projectId, session, status],
	);

	useEffect(
		() => () => {
			const editor = EditorCore.getInstance();
			if (editor.project.getActiveOrNull()?.metadata.id === projectId) void editor.save.flush();
		},
		[projectId],
	);

	const value = useMemo(() => ({ projectId, status, error, open, rebuild }), [projectId, status, error, open, rebuild]);
	return (
		<OpenCutContext.Provider value={value}>
			{status === "ready" && stage === "edit" && <EditorRuntimeBindings />}
			{children}
		</OpenCutContext.Provider>
	);
}
