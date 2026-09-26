import { expect, test } from "bun:test";
import { DUCK_PRESETS, duckKeys, speechIn } from "./ducking-plan";

const SR = 8000;
function tone({ spans, seconds }: { spans: [number, number][]; seconds: number }) {
	const samples = new Float32Array(SR * seconds);
	for (const [a, b] of spans) for (let i = a * SR; i < b * SR; i++) samples[i] = 0.3 * Math.sin(i / 3);
	return samples;
}

test("speech is found where the voice is above the threshold", () => {
	expect(speechIn({ samples: tone({ spans: [[0.5, 1.5], [5, 6]], seconds: 8 }), sampleRate: SR, threshold: -30 })).toEqual([[0.5, 1.5], [5, 6]]);
	expect(speechIn({ samples: tone({ spans: [[0.5, 1.5]], seconds: 2 }), sampleRate: SR, threshold: -5 })).toEqual([]);
});

test("close passages stay ducked through the gap; far ones release", () => {
	const moderate = DUCK_PRESETS[1];
	const { keys, passages } = duckKeys({ regions: [[0.5, 1.5], [1.7, 2.5], [5, 6]], preset: moderate, start: 0.2, duration: 7, base: -3 });
	expect(passages).toBe(2);
	const ducked = -3 + 20 * Math.log10(1 - moderate.reduction);
	expect(keys.map((k) => [Number(k.time.toFixed(2)), Number(k.value.toFixed(2))])).toEqual(
		[[0.2, -3], [0.3, ducked], [2.5, ducked], [2.8, -3], [4.7, -3], [4.8, ducked], [6, ducked], [6.3, -3]].map(([t, v]) => [t, Number(v.toFixed(2))]),
	);
});

test("speech outside the music clip is ignored and edges are clamped", () => {
	const { keys, passages } = duckKeys({ regions: [[0, 1], [20, 21]], preset: DUCK_PRESETS[1], start: 0.5, duration: 5, base: 0 });
	expect(passages).toBe(1);
	expect(keys[0].time).toBe(0);
});
