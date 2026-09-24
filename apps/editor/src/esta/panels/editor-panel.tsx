"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ApiError } from "../api";
import { type EmitProgress, emitSession, projectIdFor } from "../opencut/emit";
import { useWorkspace } from "../store";

type Built = { originals: boolean; at: number; summary: Record<string, unknown>; missing: string[] };

const builtKey = (session: string) => `esta.opencut.${session}`;

function readBuilt(session: string): Built | null {
	try {
		return JSON.parse(localStorage.getItem(builtKey(session)) || "null");
	} catch {
		return null;
	}
}

// Builds the native OpenCut project from render's <id>.openreel.json. Proxies
// are for editing; the export-bound build must reference the originals, or
// OpenCut encodes the crf-23 proxies into the finished video.
export function EditorPanel() {
	const { session } = useWorkspace();
	const [built, setBuilt] = useState<Built | null>(() => readBuilt(session));
	const [progress, setProgress] = useState<EmitProgress | null>(null);
	const [error, setError] = useState<string | null>(null);

	const build = async (originals: boolean) => {
		setError(null);
		try {
			const r = await emitSession({ session, originals, onProgress: setProgress });
			const next = { originals: r.originals, at: Date.now(), summary: r.summary, missing: r.missing };
			setBuilt(next);
			try {
				localStorage.setItem(builtKey(session), JSON.stringify(next));
			} catch {
				/* the build record just won't persist */
			}
		} catch (e) {
			setError(e instanceof ApiError && e.status === 404 ? "No render output yet: run render first." : e instanceof Error ? e.message : String(e));
		} finally {
			setProgress(null);
		}
	};

	const busy = progress !== null;
	return (
		<div className="space-y-3 p-3 text-sm">
			<div className="flex flex-wrap gap-2">
				<Button size="sm" disabled={busy} onClick={() => build(false)}>
					Build project
				</Button>
				<Button size="sm" variant="outline" disabled={busy} onClick={() => build(true)}>
					Build for export (originals)
				</Button>
				{built && !busy && (
					<Button size="sm" variant="secondary" asChild>
						<Link href={`/editor/${projectIdFor(session)}`}>Open editor</Link>
					</Button>
				)}
			</div>
			{progress && (
				<div className="text-muted-foreground text-xs">
					{progress.phase === "convert" && "Converting render output..."}
					{progress.phase === "media" && `Syncing media ${progress.done}/${progress.total}${progress.label ? `: ${progress.label}` : ""}`}
					{progress.phase === "save" && "Saving project..."}
				</div>
			)}
			{error && <div className="text-destructive text-xs">{error}</div>}
			{built && (
				<div className="space-y-1 text-xs">
					<div>
						Built {new Date(built.at).toLocaleString()} from{" "}
						<strong>{built.originals ? "originals (export-ready)" : "proxies (editing only; rebuild with originals before exporting)"}</strong>.
					</div>
					<div className="text-muted-foreground">
						{["media", "main", "overlay", "audio", "text"].map((k) => `${k} ${String(built.summary[k] ?? 0)}`).join(" · ")}
					</div>
					{built.missing.length > 0 && <div className="text-caution">Missing on disk, left out: {built.missing.join(", ")}</div>}
				</div>
			)}
		</div>
	);
}
