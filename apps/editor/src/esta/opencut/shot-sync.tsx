"use client";

import { useEffect, useRef } from "react";
import { EditorCore } from "@/core";
import type { SceneTracks } from "@/timeline";
import { useWorkspace } from "../store";

// Clips keep render's ids (clip-shot-N), so plan shot N is its clip on any
// lane, crossfade split or not.
const clipId = (shot: number) => `clip-shot-${shot}`;
const shotOf = (id: string) => {
	const m = /^clip-shot-(\d+)$/.exec(id);
	return m ? Number(m[1]) : null;
};

function locate({ tracks, id }: { tracks: SceneTracks; id: string }) {
	for (const track of [...tracks.overlay, tracks.main]) {
		const element = track.elements.find((e) => e.id === id);
		if (element) return { trackId: track.id, element };
	}
	return null;
}

// One selected shot across the planner, picker, shot strip and the OpenCut
// timeline: picking a shot selects its clip and moves the playhead to it;
// clicking a clip selects its shot everywhere else.
export function ShotSync() {
	const { selectedShot, selectShot } = useWorkspace();
	const shotRef = useRef(selectedShot);
	useEffect(() => {
		shotRef.current = selectedShot;
	});

	useEffect(() => {
		if (selectedShot == null) return;
		const editor = EditorCore.getInstance();
		const selected = editor.selection.getSelectedElements();
		if (selected.length === 1 && shotOf(selected[0].elementId) === selectedShot) return;
		const hit = locate({ tracks: editor.scenes.getActiveScene().tracks, id: clipId(selectedShot) });
		if (!hit) return;
		editor.selection.setSelectedElements({ elements: [{ trackId: hit.trackId, elementId: hit.element.id }] });
		if (!editor.playback.getIsPlaying()) editor.playback.seek({ time: hit.element.startTime });
		document.querySelector(`[data-element-id="${hit.element.id}"]`)?.scrollIntoView({ block: "nearest", inline: "center" });
	}, [selectedShot]);

	useEffect(
		() =>
			EditorCore.getInstance().selection.subscribe(() => {
				const selected = EditorCore.getInstance().selection.getSelectedElements();
				const shot = selected.length === 1 ? shotOf(selected[0].elementId) : null;
				if (shot != null && shot !== shotRef.current) selectShot(shot);
			}),
		[selectShot],
	);

	return null;
}
