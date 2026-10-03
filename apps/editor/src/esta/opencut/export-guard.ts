import { EditorCore } from "@/core";
import type { TimelineElement, TimelineTrack } from "@/timeline";
import { readBuilt } from "./host";

// Proxies are for editing only: OpenCut encodes whatever the timeline
// references, so exporting a proxied build ships a crf-23 downscale as the
// final video (v2's from_openreel.py --originals rule). Returns why export must
// wait, or null.
export function exportBlock(projectId: string): { reason: string; session: string } | null {
	if (!projectId.startsWith("esta-")) return null;
	const session = projectId.slice("esta-".length);
	const proxied = new Set(readBuilt(session)?.proxied ?? []);
	if (!proxied.size) return null;
	const tracks = EditorCore.getInstance().scenes.getActiveSceneOrNull()?.tracks;
	if (!tracks) return null;
	const all: TimelineTrack[] = [tracks.main, ...tracks.overlay, ...tracks.audio];
	const clips = all
		.flatMap((t): TimelineElement[] => t.elements)
		.filter((e) => "mediaId" in e && proxied.has(e.mediaId)).length;
	if (!clips) return null;
	return {
		session,
		reason: `${clips} clip${clips === 1 ? "" : "s"} still use downscaled editing proxies, so this export would ship a low-quality re-encode. Rebuild with Build for export (originals) in the session's Edit stage, then export.`,
	};
}
