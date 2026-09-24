"use client";

import { useEffect } from "react";
import { upsertPathKeyframe } from "@/animation";
import { EditorCore } from "@/core";
import { CanvasRenderer } from "@/services/renderer/canvas-renderer";
import { buildScene } from "@/services/renderer/scene-builder";
import type { SceneTracks, TimelineElement, TimelineTrack } from "@/timeline";
import { resolveAnimationTarget } from "@/timeline/animation-targets";
import { VOLUME_DB_MAX, VOLUME_DB_MIN } from "@/timeline/audio-constants";
import { mediaTimeFromSeconds, mediaTimeToSeconds, type MediaTime } from "@/wasm";
import { BACKEND } from "../api";
import { useChannel } from "../events";

// The live-edit channel of tools/opencut/mcp-server.mjs: commands arrive on the
// "cmd" event channel, results go back through /_ack and /_frame, and the
// timeline snapshot get_timeline reads is pushed to /_state (also the heartbeat
// the MCP server uses to tell a live editor from a dead tab).
type Key = { t: number; v: number };
type Cmd = {
	cmd: string;
	reqId?: string;
	shot?: number;
	seconds?: number;
	id?: string;
	patch?: { duration?: number; start?: number; trim_start?: number; trim_end?: number; volume?: number };
	property?: string;
	keys?: Key[];
	time?: number;
};

const sec = (t: MediaTime | undefined) => (t === undefined ? 0 : Math.round(mediaTimeToSeconds({ time: t }) * 1000) / 1000);
const ticks = (s: number) => mediaTimeFromSeconds({ seconds: Math.max(0, s) });
const toDb = (v: number) => (v > 0 ? Math.min(VOLUME_DB_MAX, Math.max(VOLUME_DB_MIN, 20 * Math.log10(v))) : VOLUME_DB_MIN);
const fromDb = (db: number) => (db <= VOLUME_DB_MIN ? 0 : Math.round(10 ** (db / 20) * 1000) / 1000);

const allTracks = (t: SceneTracks): TimelineTrack[] => [...t.overlay, t.main, ...t.audio];

// "Shot N" is the Nth clip by start time across the main track and the
// crossfade lanes (named "Main*"): the A/B split is a render device, not an
// order change.
function shots(t: SceneTracks) {
	return [t.main, ...t.overlay.filter((tr) => tr.type === "video" && tr.name.startsWith("Main"))]
		.flatMap((track) => track.elements.map((element) => ({ trackId: track.id, element })))
		.sort((a, b) => a.element.startTime - b.element.startTime);
}

function find({ t, id }: { t: SceneTracks; id: string }) {
	for (const track of allTracks(t)) {
		const element = track.elements.find((e) => e.id === id);
		if (element) return { trackId: track.id, element };
	}
	return null;
}

function snapshot(session: string) {
	const editor = EditorCore.getInstance();
	const project = editor.project.getActiveOrNull();
	const scene = editor.scenes.getActiveSceneOrNull();
	if (!project || !scene) return null;
	const shotOf = new Map(shots(scene.tracks).map((s, i) => [s.element.id, i + 1]));
	const media = new Map(editor.media.getAssets().map((m) => [m.id, m.name]));
	return {
		session,
		project: project.metadata.id,
		duration: sec(editor.timeline.getTotalDuration()),
		playhead: sec(editor.playback.getCurrentTime()),
		tracks: allTracks(scene.tracks).map((track) => ({
			id: track.id,
			name: track.name,
			type: track.type,
			...("muted" in track && { muted: track.muted }),
			clips: track.elements.map((e: TimelineElement) => ({
				id: e.id,
				...(shotOf.has(e.id) && { shot: shotOf.get(e.id) }),
				type: e.type,
				name: e.name,
				...("mediaId" in e && { media: media.get(e.mediaId) ?? e.mediaId }),
				...(e.type === "text" && { text: e.params.content }),
				start: sec(e.startTime),
				duration: sec(e.duration),
				end: Math.round((sec(e.startTime) + sec(e.duration)) * 1000) / 1000,
				...(e.sourceDuration !== undefined && { source_duration: sec(e.sourceDuration) }),
				trim_start: sec(e.trimStart),
				trim_end: sec(e.trimEnd),
				...(typeof e.params.volume === "number" && { volume: fromDb(e.params.volume) }),
				...(e.animations && { animated: Object.keys(e.animations).filter((k) => e.animations?.[k]) }),
			})),
		})),
	};
}

const post = ({ path, body }: { path: string; body: unknown }) =>
	fetch(BACKEND + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => {});

const PATHS: Record<string, string[]> = {
	opacity: ["opacity"],
	scale: ["transform.scaleX", "transform.scaleY"],
	scaleX: ["transform.scaleX"],
	scaleY: ["transform.scaleY"],
	positionX: ["transform.positionX"],
	positionY: ["transform.positionY"],
	volume: ["volume"],
};

function apply(c: Cmd): string {
	const editor = EditorCore.getInstance();
	const tracks = editor.scenes.getActiveScene().tracks;
	const update = ({ trackId, element, patch }: { trackId: string; element: TimelineElement; patch: Partial<TimelineElement> }) =>
		editor.timeline.updateElements({ updates: [{ trackId, elementId: element.id, patch }] });

	if (c.cmd === "set_duration") {
		const n = Number(c.shot);
		const list = shots(tracks);
		const hit = list[n - 1];
		if (!hit) throw new Error(`no shot ${n}: the main spine has ${list.length}`);
		update({ trackId: hit.trackId, element: hit.element, patch: { duration: ticks(Number(c.seconds)) } });
		return `shot ${n} (${hit.element.name}) is now ${Number(c.seconds)}s`;
	}

	const hit = find({ t: tracks, id: String(c.id) });
	if (!hit) throw new Error(`no clip with id ${String(c.id)}; call get_timeline for current ids`);
	const { trackId, element } = hit;

	if (c.cmd === "update_clip") {
		const p = c.patch ?? {};
		const patch: Partial<TimelineElement> = {};
		if (p.duration != null) patch.duration = ticks(p.duration);
		if (p.start != null) patch.startTime = ticks(p.start);
		if (p.trim_start != null) patch.trimStart = ticks(p.trim_start);
		if (p.trim_end != null) patch.trimEnd = ticks(p.trim_end);
		if (p.volume != null) {
			if (typeof element.params.volume !== "number") throw new Error(`${element.name} has no volume`);
			patch.params = { ...element.params, volume: toDb(p.volume) };
		}
		update({ trackId, element, patch });
		return `${element.name}: ${Object.keys(p).join(", ")} updated`;
	}

	if (c.cmd === "animate_clip") {
		const paths = PATHS[String(c.property)];
		if (!paths) throw new Error(`can't animate ${String(c.property)}`);
		const keys = c.keys ?? [];
		let animations = { ...element.animations };
		for (const path of paths) {
			const target = resolveAnimationTarget({ element, path });
			if (!target) throw new Error(`${element.name} (${element.type}) has no ${path}`);
			// The keys replace whatever the property had, as the tool describes.
			delete animations[path];
			for (const k of keys)
				animations =
					upsertPathKeyframe({
						animations,
						propertyPath: path,
						time: ticks(Math.min(k.t, sec(element.duration))),
						value: path === "volume" ? toDb(k.v) : k.v,
						interpolation: "linear",
						channelLayout: target.channelLayout,
						coerceValue: target.coerceValue,
					}) ?? animations;
		}
		update({ trackId, element, patch: { animations } });
		return `${element.name}: ${keys.length} ${String(c.property)} keys`;
	}

	throw new Error(`unknown command ${c.cmd}`);
}

async function renderFrame(time: number) {
	const editor = EditorCore.getInstance();
	const { canvasSize, background, fps } = editor.project.getActive().settings;
	const scene = buildScene({
		tracks: editor.scenes.getActiveScene().tracks,
		mediaAssets: editor.media.getAssets(),
		duration: editor.timeline.getTotalDuration() || ticks(1),
		canvasSize,
		background,
	});
	const renderer = new CanvasRenderer({ width: canvasSize.width, height: canvasSize.height, fps });
	const full = document.createElement("canvas");
	full.width = canvasSize.width;
	full.height = canvasSize.height;
	await renderer.renderToCanvas({ node: scene, time: ticks(time), targetCanvas: full });
	// Downscaled: the frame goes into Claude's context.
	const scale = Math.min(1, 540 / Math.max(canvasSize.width, canvasSize.height));
	const out = document.createElement("canvas");
	out.width = Math.round(canvasSize.width * scale);
	out.height = Math.round(canvasSize.height * scale);
	out.getContext("2d")?.drawImage(full, 0, 0, out.width, out.height);
	return { image: out.toDataURL("image/jpeg", 0.8), w: out.width, h: out.height };
}

export function EstaCmdBridge({ session }: { session: string }) {
	useChannel<Cmd>({
		ch: "cmd",
		fn: (c) => {
			if (c.cmd === "get_frame") {
				renderFrame(Number(c.time) || 0)
					.then((f) => post({ path: "/_frame", body: { reqId: c.reqId, ...f } }))
					.catch((e) => post({ path: "/_frame", body: { reqId: c.reqId, error: e instanceof Error ? e.message : String(e) } }));
				return;
			}
			try {
				post({ path: "/_ack", body: { reqId: c.reqId, applied: true, message: apply(c) } });
			} catch (e) {
				post({ path: "/_ack", body: { reqId: c.reqId, applied: false, message: e instanceof Error ? e.message : String(e) } });
			}
		},
	});

	useEffect(() => {
		const editor = EditorCore.getInstance();
		let queued: ReturnType<typeof setTimeout> | null = null;
		const push = () => {
			const s = snapshot(session);
			if (s) void post({ path: "/_state", body: s });
		};
		const soon = () => {
			if (!queued) queued = setTimeout(() => ((queued = null), push()), 300);
		};
		push();
		const beat = setInterval(push, 2000);
		const unsubs = [editor.timeline.subscribe(soon), editor.scenes.subscribe(soon)];
		return () => {
			clearInterval(beat);
			if (queued) clearTimeout(queued);
			for (const u of unsubs) u();
		};
	}, [session]);

	return null;
}
