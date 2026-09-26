import { VOLUME_DB_MIN } from "@/timeline/audio-constants";

// Ducking dips the music clip wherever the voice track has speech, as volume
// keyframes. Presets and their fields are v2's AudioDuckingSection (threshold
// dBFS, reduction as a fraction of the level, times in seconds).
export const DUCK_PRESETS = [
	{ id: "subtle", label: "Subtle", threshold: -35, reduction: 0.4, attack: 0.15, release: 0.5, hold: 0.2 },
	{ id: "moderate", label: "Moderate", threshold: -30, reduction: 0.6, attack: 0.1, release: 0.3, hold: 0.2 },
	{ id: "aggressive", label: "Aggressive", threshold: -25, reduction: 0.8, attack: 0.05, release: 0.2, hold: 0.2 },
	{ id: "podcast", label: "Podcast", threshold: -28, reduction: 0.75, attack: 0.08, release: 0.4, hold: 0.3 },
] as const;
export type DuckPreset = (typeof DUCK_PRESETS)[number];

const WINDOW = 0.02;

// Speech as [start, end] seconds into the source: 20 ms windows whose RMS is
// above the threshold.
export function speechIn({ samples, sampleRate, threshold }: { samples: Float32Array; sampleRate: number; threshold: number }) {
	const size = Math.max(1, Math.round(sampleRate * WINDOW));
	const floor = 10 ** (threshold / 20);
	const found: [number, number][] = [];
	for (let i = 0; i < samples.length; i += size) {
		let sum = 0;
		const end = Math.min(samples.length, i + size);
		for (let j = i; j < end; j++) sum += samples[j] * samples[j];
		if (Math.sqrt(sum / (end - i)) < floor) continue;
		const s = i / sampleRate;
		const last = found.at(-1);
		if (last && s - last[1] < WINDOW * 1.5) last[1] = end / sampleRate;
		else found.push([s, end / sampleRate]);
	}
	return found;
}

// Volume keys (seconds into the music clip, dB) for the given speech regions.
// Regions closer than a release plus an attack stay ducked through the gap, so
// the music doesn't pump between words.
export function duckKeys({ regions, preset, start, duration, base }: { regions: [number, number][]; preset: DuckPreset; start: number; duration: number; base: number }) {
	const ducked = Math.max(VOLUME_DB_MIN, base + 20 * Math.log10(1 - preset.reduction));
	const spans: [number, number][] = [];
	for (const [a, b] of regions) {
		const s = a - start;
		const e = b - start + preset.hold;
		if (e <= 0 || s >= duration) continue;
		const last = spans.at(-1);
		if (last && s - last[1] < preset.attack + preset.release) last[1] = Math.max(last[1], e);
		else spans.push([s, e]);
	}
	const keys: { time: number; value: number }[] = [];
	for (const [s, e] of spans) {
		if (s - preset.attack > 0) keys.push({ time: s - preset.attack, value: base });
		keys.push({ time: Math.max(0, s), value: ducked });
		keys.push({ time: Math.min(duration, e), value: ducked });
		if (e + preset.release < duration) keys.push({ time: e + preset.release, value: base });
	}
	return { keys, passages: spans.length };
}
