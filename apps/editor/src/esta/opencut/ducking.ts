import { removeElementKeyframe, upsertPathKeyframe } from "@/animation";
import { getChannelsFromData } from "@/animation/channel-data";
import { decodeAudioToFloat32 } from "@/media/audio";
import type { MediaAsset } from "@/media/types";
import type { AudioElement, TimelineElement } from "@/timeline";
import { resolveAnimationTarget } from "@/timeline/animation-targets";
import { mediaTimeFromSeconds, mediaTimeToSeconds, type MediaTime } from "@/wasm";
import { speechIn } from "./ducking-plan";

// Keyframe ids carry a tag (esta-duck|n) so a re-apply replaces them and
// Remove takes them out, leaving the clip's own volume keys alone.
const TAG = "esta-duck";
const RATE = 8000;

const secs = (t: MediaTime | undefined) => (t === undefined ? 0 : mediaTimeToSeconds({ time: t }));
const rateOf = (e: TimelineElement) => ("retime" in e && e.retime?.rate) || 1;

// Speech regions on the timeline, from every voice clip on the source track.
export async function voiceRegions({ clips, assets, threshold }: { clips: TimelineElement[]; assets: MediaAsset[]; threshold: number }) {
	const regions: [number, number][] = [];
	for (const clip of clips) {
		if (clip.type !== "audio" || clip.sourceType !== "upload") continue;
		const asset = assets.find((a) => a.id === clip.mediaId);
		if (!asset?.file) continue;
		const { samples, sampleRate } = await decodeAudioToFloat32({ audioBlob: asset.file, sampleRate: RATE });
		const rate = rateOf(clip);
		const from = secs(clip.trimStart);
		const to = from + secs(clip.duration) * rate;
		for (const [a, b] of speechIn({ samples, sampleRate, threshold })) {
			if (b <= from || a >= to) continue;
			const at = (s: number) => secs(clip.startTime) + (Math.min(Math.max(s, from), to) - from) / rate;
			regions.push([at(a), at(b)]);
		}
	}
	return regions.sort((x, y) => x[0] - y[0]);
}

const volumeKeyIds = (element: TimelineElement) => {
	const data = element.animations?.volume;
	return data ? getChannelsFromData({ data }).flatMap((c) => c.keys.map((k) => k.id)) : [];
};

export const isDucked = (element: TimelineElement) => volumeKeyIds(element).some((id) => id.startsWith(`${TAG}|`));
export const hasOwnVolumeKeys = (element: TimelineElement) => volumeKeyIds(element).some((id) => !id.startsWith(`${TAG}|`));

export function stripDuck<T extends TimelineElement>(element: T): T {
	let animations = element.animations;
	for (const id of volumeKeyIds(element)) if (id.startsWith(`${TAG}|`)) animations = removeElementKeyframe({ animations, propertyPath: "volume", keyframeId: id });
	return { ...element, animations };
}

export function withDuck({ element, keys }: { element: AudioElement; keys: { time: number; value: number }[] }): AudioElement {
	const target = resolveAnimationTarget({ element, path: "volume" });
	if (!target) return element;
	let animations = stripDuck(element).animations;
	keys.forEach((k, n) => {
		animations = upsertPathKeyframe({
			animations,
			propertyPath: "volume",
			time: mediaTimeFromSeconds({ seconds: k.time }),
			value: k.value,
			interpolation: "linear",
			keyframeId: `${TAG}|${n}`,
			channelLayout: target.channelLayout,
			coerceValue: target.coerceValue,
		});
	});
	return { ...element, animations };
}
