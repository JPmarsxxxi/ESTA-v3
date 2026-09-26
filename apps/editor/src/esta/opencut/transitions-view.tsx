"use client";

import { useState } from "react";
import { Command } from "@/commands/base-command";
import { EditorCore } from "@/core";
import { useEditor } from "@/editor/use-editor";
import type { SceneTracks, TimelineElement, VideoTrack } from "@/timeline";
import { generateUUID } from "@/utils/id";
import { type MediaTime, mediaTimeToSeconds } from "@/wasm";
import { shots } from "./tracks";
import { TRANSITIONS, type TransitionType, applyKeys, baseXOf, extendOut, planTransition, readTransition, spareOf, stripTransition } from "./transitions";

class TracksCommand extends Command {
	private saved: SceneTracks | null = null;
	private readonly next: (tracks: SceneTracks) => SceneTracks;
	constructor({ next }: { next: (tracks: SceneTracks) => SceneTracks }) {
		super();
		this.next = next;
	}
	execute() {
		const editor = EditorCore.getInstance();
		this.saved = editor.scenes.getActiveScene().tracks;
		editor.timeline.updateTracks(this.next(this.saved));
		return undefined;
	}
	undo() {
		if (this.saved) EditorCore.getInstance().timeline.updateTracks(this.saved);
	}
}

const secs = (t: MediaTime) => mediaTimeToSeconds({ time: t });
const LANE_B = "Main B";

function replace({ tracks, id, element }: { tracks: SceneTracks; id: string; element: TimelineElement }): SceneTracks {
	const swap = <T extends { elements: TimelineElement[] }>(track: T): T => ({ ...track, elements: track.elements.map((e) => (e.id === id ? element : e)) });
	return { ...tracks, main: swap(tracks.main) as VideoTrack, overlay: tracks.overlay.map((t) => swap(t) as typeof t) };
}

// The two clips of a cut must sit on different lanes to overlap; the incoming
// one moves up to the crossfade lane (created just above the main track).
function toLaneB({ tracks, element }: { tracks: SceneTracks; element: TimelineElement }): SceneTracks | string {
	const lane = tracks.overlay.find((t): t is VideoTrack => t.type === "video" && t.name === LANE_B);
	const end = element.startTime + element.duration;
	if (lane?.elements.some((e) => e.startTime < end && e.startTime + e.duration > element.startTime)) return `the ${LANE_B} lane is taken there`;
	if (element.type !== "video" && element.type !== "image") return "only video and image clips take a transition";
	const moved = element;
	const strip = <T extends { elements: TimelineElement[] }>(t: T): T => ({ ...t, elements: t.elements.filter((e) => e.id !== element.id) });
	const overlay = tracks.overlay.map((t) => strip(t) as typeof t);
	const target: VideoTrack = lane ? { ...lane, elements: [...lane.elements, moved] } : { id: generateUUID(), name: LANE_B, type: "video", elements: [moved], muted: tracks.main.muted, hidden: false };
	return { ...tracks, main: strip(tracks.main), overlay: lane ? overlay.map((t) => (t.id === lane.id ? target : t)) : [...overlay, target] };
}

function setTransition({ tracks, aId, bId, type, duration, width }: { tracks: SceneTracks; aId: string; bId: string; type: TransitionType | "none"; duration: number; width: number }): SceneTracks | string {
	const cut = shots(tracks);
	const a = cut.find((s) => s.element.id === aId);
	const b = cut.find((s) => s.element.id === bId);
	if (!a || !b) return "the cut changed; try again";
	let next = replace({ tracks, id: aId, element: stripTransition({ element: a.element, side: "out" }) });
	next = replace({ tracks: next, id: bId, element: stripTransition({ element: b.element, side: "in" }) });
	if (type === "none") return next;
	const def = TRANSITIONS.find((x) => x.type === type);
	if (def?.overlap && a.trackId === b.trackId) {
		const moved = toLaneB({ tracks: next, element: shots(next).find((s) => s.element.id === bId)?.element ?? b.element });
		if (typeof moved === "string") return moved;
		next = moved;
	}
	const now = shots(next);
	const A = now.find((s) => s.element.id === aId);
	const B = now.find((s) => s.element.id === bId);
	if (!A || !B) return "the cut changed; try again";
	const z = (trackId: string) => (trackId === next.main.id ? 0 : next.overlay.length - next.overlay.findIndex((t) => t.id === trackId));
	const laneA = [next.main, ...next.overlay].find((t) => t.id === A.trackId);
	const aEnd = A.element.startTime + A.element.duration;
	const following = laneA?.elements.filter((e) => e.startTime >= aEnd).sort((x, y) => x.startTime - y.startTime)[0];
	const room = following ? secs(following.startTime) - secs(A.element.startTime) - secs(A.element.duration) : Number.POSITIVE_INFINITY;
	const plan = planTransition({
		type,
		duration,
		a: { duration: secs(A.element.duration), spare: Math.min(spareOf(A.element), room), top: z(A.trackId) > z(B.trackId), baseX: baseXOf(A.element) },
		b: { duration: secs(B.element.duration), spare: 0, top: z(B.trackId) > z(A.trackId), baseX: baseXOf(B.element) },
		width,
	});
	if (!plan) return "no footage left after the outgoing shot to overlap";
	next = replace({ tracks: next, id: aId, element: applyKeys({ element: extendOut({ element: A.element, run: plan.run }), keys: plan.out }) });
	return replace({ tracks: next, id: bId, element: applyKeys({ element: B.element, keys: plan.in }) });
}

// Fills OpenCut's Transitions tab: one row per cut between consecutive shots.
export function TransitionsView() {
	const tracks = useEditor((e) => e.scenes.getActiveSceneOrNull()?.tracks ?? null);
	const width = useEditor((e) => e.project.getActiveOrNull()?.settings.canvasSize.width ?? 1080);
	const [error, setError] = useState<string | null>(null);
	const list = tracks ? shots(tracks) : [];

	const apply = ({ aId, bId, type, duration }: { aId: string; bId: string; type: TransitionType | "none"; duration: number }) => {
		const editor = EditorCore.getInstance();
		const result = setTransition({ tracks: editor.scenes.getActiveScene().tracks, aId, bId, type, duration, width });
		if (typeof result === "string") return setError(result);
		setError(null);
		editor.command.execute({ command: new TracksCommand({ next: () => result }) });
	};

	if (list.length < 2) return <div className="text-muted-foreground p-4 text-sm">Transitions go between shots; this timeline has fewer than two.</div>;
	return (
		<div className="h-full space-y-2 overflow-y-auto p-3 text-sm">
			{error && <div className="text-destructive text-xs">{error}</div>}
			{list.slice(1).map((b, i) => {
				const a = list[i];
				const current = readTransition({ element: b.element, side: "in" }) ?? readTransition({ element: a.element, side: "out" });
				const type = current?.type ?? "none";
				const duration = current?.duration ?? 0.5;
				return (
					<div key={b.element.id} className="flex items-center gap-2">
						<button
							type="button"
							className="text-muted-foreground hover:text-foreground w-20 shrink-0 text-left text-xs"
							onClick={() => EditorCore.getInstance().playback.seek({ time: b.element.startTime })}
							title={`${a.element.name} → ${b.element.name}`}
						>
							Shot {i + 1} → {i + 2}
						</button>
						<select
							aria-label={`Transition into shot ${i + 2}`}
							className="bg-background min-w-0 flex-1 rounded border px-1 py-0.5 text-xs"
							value={type}
							onChange={(e) => apply({ aId: a.element.id, bId: b.element.id, type: TRANSITIONS.find((t) => t.type === e.target.value)?.type ?? "none", duration })}
						>
							<option value="none">Cut</option>
							{TRANSITIONS.map((t) => (
								<option key={t.type} value={t.type}>
									{t.label}
								</option>
							))}
						</select>
						<input
							aria-label={`Length of transition into shot ${i + 2}`}
							type="number"
							min={0.1}
							max={3}
							step={0.1}
							disabled={type === "none"}
							className="bg-background w-14 rounded border px-1 py-0.5 text-xs"
							defaultValue={duration}
							key={`${type}-${duration}`}
							onBlur={(e) => {
								const d = Number(e.target.value);
								if (d > 0 && d !== duration) apply({ aId: a.element.id, bId: b.element.id, type, duration: d });
							}}
						/>
						<span className="text-muted-foreground text-xs">s</span>
					</div>
				);
			})}
		</div>
	);
}
