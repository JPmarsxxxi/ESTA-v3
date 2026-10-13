"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ExportButton } from "@/components/editor/export-button";
import { exportBlock } from "../opencut/export-guard";
import { useOpenCut } from "../opencut/host";

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

// One line for the auto-build: progress while it runs, the error and what's
// missing when it fails, never a silent empty timeline.
export function BuildStatus() {
	const { status, built, progress, buildError, build } = useOpenCut();
	if (progress)
		return (
			<span className="text-muted-foreground truncate">
				{progress.phase === "convert" && "Building the project from render..."}
				{progress.phase === "media" && `Syncing media ${progress.done}/${progress.total}`}
				{progress.phase === "save" && "Saving project..."}
			</span>
		);
	if (buildError)
		return (
			<span className="flex min-w-0 items-center gap-2">
				<span className="text-destructive truncate" title={buildError}>
					Build failed: {buildError}
				</span>
				<Button size="sm" variant="outline" className="h-6 text-xs" onClick={() => build(built?.originals ?? false)}>
					Retry
				</Button>
			</span>
		);
	if (built?.missing.length)
		return (
			<span className="text-caution truncate" title={built.missing.join(", ")}>
				{built.missing.length} missing on disk, left out
			</span>
		);
	if (status === "loading") return <span className="text-muted-foreground">Loading the project...</span>;
	return null;
}

// Export from a proxied build rebuilds from the originals first, so the user
// never has to pick between the two builds (export-guard.ts explains why).
export function EstaExport() {
	const { projectId, status, build } = useOpenCut();
	if (status !== "ready") return null;
	return (
		<ExportButton
			prepare={async () => {
				if (!exportBlock(projectId)) return true;
				await build(true);
				return !exportBlock(projectId);
			}}
		/>
	);
}

// Detailed view only: what the last build used and produced.
export function EditorPanel() {
	const { projectId, built, progress } = useOpenCut();
	return (
		<div className="text-sm">
			<ConflictBanner />
			<div className="space-y-3 p-3">
				<div className="flex flex-wrap items-center gap-2 text-xs">
					<BuildStatus />
					{built && !progress && (
						<Button size="sm" variant="secondary" asChild>
							<Link href={`/editor/${projectId}`}>Full-page editor</Link>
						</Button>
					)}
				</div>
				{!built && !progress && <div className="text-muted-foreground text-xs">The project builds itself once render has written its output.</div>}
				{built && (
					<div className="space-y-1 text-xs">
						<div>
							Built {new Date(built.at).toLocaleString()} from <strong>{built.originals ? "originals (export-ready)" : "proxies (Export rebuilds from originals first)"}</strong>. It
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
