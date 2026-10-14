"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ExportButton } from "@/components/editor/export-button";
import { useEditor } from "@/editor/use-editor";
import { useOpenCut } from "../opencut/host";
import { useWorkspace } from "../store";

// Chrome defers media loading in hidden tabs, so a build or export in a minimised window stalls without an
// error. Say so instead of looking hung (SPEC.md Part 12, F7).
function useHiddenWhileBusy(busy: boolean): boolean {
	const [hidden, setHidden] = useState(false);
	useEffect(() => {
		if (!busy) return;
		const check = () => {
			if (document.visibilityState === "hidden") setHidden(true);
		};
		document.addEventListener("visibilitychange", check);
		const first = setTimeout(check, 0);
		return () => {
			clearTimeout(first);
			document.removeEventListener("visibilitychange", check);
			setHidden(false);
		};
	}, [busy]);
	return busy && hidden;
}

export function ConflictBanner() {
	const { conflict, built, build, keepMine } = useOpenCut();
	if (!conflict || !built) return null;
	return (
		<div className="bg-caution/15 flex flex-wrap items-center gap-2 border-b px-2 py-1.5 text-xs">
			<span className="flex-1">Render updated the project, and the timeline has edits of yours since the last build.</span>
			<Button size="sm" variant="outline" className="h-6 text-xs" onClick={keepMine}>
				Keep mine
			</Button>
			<Button size="sm" className="h-6 text-xs" onClick={() => build(built.originals)}>
				Take render&apos;s
			</Button>
		</div>
	);
}

// Builds the native OpenCut project from render's <id>.openreel.json. Proxies
// are for editing; the export-bound build must reference the originals, or
// OpenCut encodes the crf-23 proxies into the finished video.
export function EditorPanel() {
	const { projectId, status, built, progress, buildError, build } = useOpenCut();
	const { session } = useWorkspace();
	const exporting = useEditor((e) => e.project.getExportState().isExporting);
	const busy = progress !== null;
	const hidden = useHiddenWhileBusy(busy || exporting);
	return (
		<div className="text-sm">
			<ConflictBanner />
			<div className="space-y-3 p-3">
				<div className="flex flex-wrap gap-2">
					<Button size="sm" disabled={busy} onClick={() => build(false)}>
						Build project
					</Button>
					<Button size="sm" variant="outline" disabled={busy} onClick={() => build(true)}>
						Build for export (originals)
					</Button>
					{built && !busy && status === "ready" && <ExportButton />}
					{built && !busy && (
						<Button size="sm" variant="secondary" asChild>
							<Link href={`/editor/${projectId}`}>Full-page editor</Link>
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
				{hidden && (
					<div className="text-caution text-xs">
						This tab was hidden during the {busy ? "build" : "export"}: Chrome holds back media loading in hidden tabs, so it
						stalls until the tab is visible again. Keep this tab in front, or export unattended with{" "}
						<code>bun run export {session}</code>.
					</div>
				)}
				{buildError && <div className="text-destructive text-xs">{buildError}</div>}
				{built && (
					<div className="space-y-1 text-xs">
						<div>
							Built {new Date(built.at).toLocaleString()} from{" "}
							<strong>{built.originals ? "originals (export-ready)" : "proxies (editing only; rebuild with originals before exporting)"}</strong>. It
							follows render from here on.
						</div>
						<div className="text-muted-foreground">
							{["media", "main", "overlay", "audio", "text", "pending", "hydrated"].map((k) => `${k} ${String(built.summary[k] ?? 0)}`).join(" · ")}
						</div>
						{built.missing.length > 0 && <div className="text-caution">Missing on disk, left out: {built.missing.join(", ")}</div>}
					</div>
				)}
			</div>
		</div>
	);
}
