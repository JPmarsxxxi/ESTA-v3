import { removeElementKeyframe, upsertPathKeyframe } from "@/animation";
import { getChannelsFromData } from "@/animation/channel-data";
import type { TimelineElement } from "@/timeline";
import { resolveAnimationTarget } from "@/timeline/animation-targets";
import { type MediaTime, mediaTimeFromSeconds, mediaTimeToSeconds } from "@/wasm";

// OpenCut has no transition object, so a transition is the two clips of a cut
// overlapping on different lanes plus keyframes on them. Those keyframes carry
// a tagged id (esta-tx|side|type|duration|run|n), which is how a transition is
// read back, changed and removed. `run` is how far the outgoing clip was
// extended past the cut to create the overlap.
export const TRANSITIONS = [
	{ type: "crossfade", label: "Crossfade", overlap: true },
	{ type: "dip-black", label: "Dip to black", overlap: false },
	{ type: "slide", label: "Slide", overlap: true },
	{ type: "push", label: "Push", overlap: true },
] as const;
export type TransitionType = (typeof TRANSITIONS)[number]["type"];

type Side = "in" | "out";
export type PlannedKey = { id: string; property: "opacity" | "transform.positionX"; time: number; value: number };
// Seconds. `spare`: how far the outgoing clip can run past its end (source left
// over; unlimited for stills). `top`: whether the clip draws above the other.
export type ClipSide = { duration: number; spare: number; top: boolean; baseX: number };

const TAG = "esta-tx";

export function planTransition({ type, duration, a, b, width }: { type: TransitionType; duration: number; a: ClipSide; b: ClipSide; width: number }) {
	const def = TRANSITIONS.find((x) => x.type === type);
	if (!def) return null;
	const run = def.overlap ? Math.min(duration, a.spare, b.duration) : 0;
	if (def.overlap && run < 0.02) return null;
	const tag = (side: Side) => `${TAG}|${side}|${type}|${duration}|${run}`;
	let n = 0;
	const key = ({ side, property, time, value }: { side: Side; property: PlannedKey["property"]; time: number; value: number }): PlannedKey => ({ id: `${tag(side)}|${n++}`, property, time, value });
	const op = (side: Side, time: number, value: number) => key({ side, property: "opacity", time, value }); // eslint-disable-line opencut/prefer-object-params
	const px = (side: Side, time: number, value: number) => key({ side, property: "transform.positionX", time, value }); // eslint-disable-line opencut/prefer-object-params
	const end = a.duration;
	const out: PlannedKey[] = [];
	const inn: PlannedKey[] = [];
	if (type === "crossfade") {
		// Whichever clip is on top fades; the one underneath keeps a marker pair.
		if (b.top) inn.push(op("in", 0, 0), op("in", run, 1));
		else inn.push(op("in", 0, 1), op("in", run, 1));
		if (b.top) out.push(op("out", end, 1), op("out", end + run, 1));
		else out.push(op("out", end, 1), op("out", end + run, 0));
	} else if (type === "dip-black") {
		const half = Math.min(duration / 2, a.duration / 2, b.duration / 2);
		out.push(op("out", end - half, 1), op("out", end, 0));
		inn.push(op("in", 0, 0), op("in", half, 1));
	} else if (type === "slide") {
		// The upper clip moves: the incoming one slides in, or the outgoing one slides away.
		if (b.top) {
			inn.push(px("in", 0, b.baseX + width), px("in", run, b.baseX));
			out.push(op("out", end, 1), op("out", end + run, 1));
		} else {
			out.push(px("out", end, a.baseX), px("out", end + run, a.baseX - width));
			inn.push(op("in", 0, 1), op("in", run, 1));
		}
	} else {
		out.push(px("out", end, a.baseX), px("out", end + run, a.baseX - width));
		inn.push(px("in", 0, b.baseX + width), px("in", run, b.baseX));
	}
	return { run, out, in: inn };
}

function taggedKeys(element: TimelineElement) {
	const found: { path: string; id: string }[] = [];
	for (const [path, data] of Object.entries(element.animations ?? {}))
		for (const channel of getChannelsFromData({ data }))
			for (const k of channel.keys) if (k.id.startsWith(`${TAG}|`)) found.push({ path, id: k.id });
	return found;
}

export function readTransition({ element, side }: { element: TimelineElement; side: Side }) {
	const hit = taggedKeys(element).find((k) => k.id.split("|")[1] === side);
	if (!hit) return null;
	const [, , type, duration, run] = hit.id.split("|");
	const def = TRANSITIONS.find((x) => x.type === type);
	return def ? { type: def.type, duration: Number(duration), run: Number(run) } : null;
}

const ticks = (s: number) => mediaTimeFromSeconds({ seconds: Math.max(0, s) });
const secs = (t: MediaTime | undefined) => (t === undefined ? 0 : mediaTimeToSeconds({ time: t }));
const rateOf = (e: TimelineElement) => ("retime" in e && e.retime?.rate) || 1;

// Removes one side of a transition; the outgoing side also gives back the
// overlap it was extended by.
export function stripTransition<T extends TimelineElement>({ element, side }: { element: T; side: Side }): T {
	const current = readTransition({ element, side });
	if (!current) return element;
	let animations = element.animations;
	for (const k of taggedKeys(element)) if (k.id.split("|")[1] === side) animations = removeElementKeyframe({ animations, propertyPath: k.path, keyframeId: k.id });
	const next = { ...element, animations };
	if (side !== "out" || current.run <= 0) return next;
	return {
		...next,
		duration: ticks(secs(element.duration) - current.run),
		...(element.type === "video" && { trimEnd: ticks(secs(element.trimEnd) + current.run * rateOf(element)) }),
	};
}

export function applyKeys<T extends TimelineElement>({ element, keys }: { element: T; keys: PlannedKey[] }): T {
	let animations = element.animations;
	for (const k of keys) {
		const target = resolveAnimationTarget({ element: { ...element, animations }, path: k.property });
		if (!target) continue;
		animations = upsertPathKeyframe({
			animations,
			propertyPath: k.property,
			time: ticks(k.time),
			value: k.value,
			interpolation: "linear",
			keyframeId: k.id,
			channelLayout: target.channelLayout,
			coerceValue: target.coerceValue,
		});
	}
	return { ...element, animations };
}

export function extendOut<T extends TimelineElement>({ element, run }: { element: T; run: number }): T {
	if (run <= 0) return element;
	return {
		...element,
		duration: ticks(secs(element.duration) + run),
		...(element.type === "video" && { trimEnd: ticks(Math.max(0, secs(element.trimEnd) - run * rateOf(element))) }),
	};
}

export const spareOf = (e: TimelineElement) => (e.type === "video" ? secs(e.trimEnd) / rateOf(e) : Number.POSITIVE_INFINITY);
export const baseXOf = (e: TimelineElement) => (typeof e.params["transform.positionX"] === "number" ? e.params["transform.positionX"] : 0);
