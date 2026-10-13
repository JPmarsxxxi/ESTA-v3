"use client";

import { useEffect, useState } from "react";
import { EditorCore } from "@/core";
import { mediaTimeToSeconds, type MediaTime } from "@/wasm";
import { allTracks } from "./tracks";

// Plan shot N keeps render's clip id (clip-shot-N) through the build.
export const shotOfClip = (id: string) => {
	const m = /^clip-shot-(\d+)$/.exec(id);
	return m ? Number(m[1]) : null;
};

export type SelectedClip = {
	id: string;
	trackId: string;
	track: string;
	type: string;
	shot: number | null;
	name: string;
	media: string | null;
	start: number;
	in: number;
	out: number;
};

export type TimelineSelection = { clips: SelectedClip[]; track: { id: string; name: string; type: string } | null; key: string };

const EMPTY: TimelineSelection = { clips: [], track: null, key: "" };
const sec = (t: MediaTime) => Math.round(mediaTimeToSeconds({ time: t }) * 100) / 100;

export function readSelection(): TimelineSelection {
	const editor = EditorCore.getInstance();
	const scene = editor.scenes.getActiveSceneOrNull();
	const refs = editor.selection.getSelectedElements();
	if (!scene) return EMPTY;
	const media = new Map(editor.media.getAssets().map((m) => [m.id, m.name]));
	const tracks = allTracks(scene.tracks);
	const clips: SelectedClip[] = [];
	for (const ref of refs) {
		const track = tracks.find((t) => t.id === ref.trackId);
		const e = track?.elements.find((el) => el.id === ref.elementId);
		if (!track || !e) continue;
		clips.push({
			id: e.id,
			trackId: track.id,
			track: track.name,
			type: e.type,
			shot: shotOfClip(e.id),
			name: e.name,
			media: "mediaId" in e ? (media.get(e.mediaId) ?? e.mediaId) : null,
			start: sec(e.startTime),
			in: sec(e.trimStart),
			out: sec(e.trimStart) + sec(e.duration),
		});
	}
	clips.sort((a, b) => a.start - b.start);
	const trackId = editor.selection.getSelectedTrackId();
	const t = trackId ? tracks.find((tr) => tr.id === trackId) : null;
	return {
		clips,
		track: t ? { id: t.id, name: t.name, type: t.type } : null,
		key: `${trackId ?? ""}|${clips.map((c) => c.id).join(",")}`,
	};
}

// The live timeline selection, also while no project is loaded (empty then).
export function useTimelineSelection() {
	const [sel, setSel] = useState<TimelineSelection>(readSelection);
	useEffect(() => {
		const editor = EditorCore.getInstance();
		const update = () => setSel((prev) => {
			const next = readSelection();
			return next.key === prev.key ? prev : next;
		});
		update();
		const unsubs = [editor.selection.subscribe(update), editor.scenes.subscribe(update), editor.timeline.subscribe(update)];
		return () => {
			for (const u of unsubs) u();
		};
	}, []);
	return sel;
}

function shotRange(shots: number[]) {
	const sorted = [...shots].sort((a, b) => a - b);
	const contiguous = sorted.every((n, i) => i === 0 || n === sorted[i - 1] + 1);
	return contiguous && sorted.length > 2 ? `${sorted[0]}-${sorted[sorted.length - 1]}` : sorted.join(", ");
}

// The chip text: "3 clips: shots 12-14 (main)", "audio: voice", "track: graphics".
export function selectionLabel(sel: TimelineSelection): string | null {
	if (sel.track) return `track: ${sel.track.name}`;
	if (!sel.clips.length) return null;
	const tracks = [...new Set(sel.clips.map((c) => c.track))].join(", ");
	const shots = sel.clips.flatMap((c) => (c.shot === null ? [] : [c.shot]));
	if (sel.clips.length === 1) {
		const c = sel.clips[0];
		if (c.shot !== null) return `shot ${c.shot} (${c.track})`;
		return `${c.type}: ${c.type === "audio" ? c.track : c.name}`;
	}
	const what = shots.length === sel.clips.length ? `shot${shots.length === 1 ? "" : "s"} ${shotRange(shots)}` : shots.length ? `shots ${shotRange(shots)} + ${sel.clips.length - shots.length} more` : "";
	return `${sel.clips.length} clips${what ? `: ${what}` : ""} (${tracks})`;
}

// Prepended to a chat turn: Claude needs the element ids for the live-edit MCP
// tools and the shot numbers for the pipeline skills.
export function selectionBlock(sel: TimelineSelection): string {
	const tracks = sel.track ? [sel.track.name] : [...new Set(sel.clips.map((c) => c.track))];
	const shots = sel.clips.flatMap((c) => (c.shot === null ? [] : [c.shot]));
	const lines = sel.clips.map(
		(c) =>
			`- ${c.shot !== null ? `shot ${c.shot}` : `not a plan shot (${c.type} "${c.name}")`} · track ${c.track} · ${c.media ?? c.name} · in ${c.in}s out ${c.out}s · at ${c.start}s · id ${c.id}`,
	);
	if (sel.track) lines.unshift(`- whole track "${sel.track.name}" (${sel.track.type}), ${sel.clips.length} clips`);
	return [`[selection: clips=${sel.clips.map((c) => c.id).join(",")} shots=${shots.join(",")} tracks=${tracks.join(",")}]`, ...lines, "[/selection]"].join("\n");
}
