import type { SceneTracks, TimelineTrack } from "@/timeline";

export const allTracks = (t: SceneTracks): TimelineTrack[] => [...t.overlay, t.main, ...t.audio];

// "Shot N" is the Nth clip by start time across the main track and the
// crossfade lanes (named "Main*"): the A/B split is a render device, not an
// order change.
export function shots(t: SceneTracks) {
	return [t.main, ...t.overlay.filter((tr) => tr.type === "video" && tr.name.startsWith("Main"))]
		.flatMap((track) => track.elements.map((element) => ({ trackId: track.id, element })))
		.sort((a, b) => a.element.startTime - b.element.startTime);
}

export function find({ t, id }: { t: SceneTracks; id: string }) {
	for (const track of allTracks(t)) {
		const element = track.elements.find((e) => e.id === id);
		if (element) return { trackId: track.id, element };
	}
	return null;
}
