import type { EffectDefinition } from "@/effects/types";

const num = ({ params, key }: { params: Record<string, unknown>; key: string }) => {
	const raw = params[key];
	return typeof raw === "number" ? raw : Number.parseFloat(String(raw)) || 0;
};

// Basic colour correction, for matching stock clips from different sources.
// The shader ("color-adjust", rust/crates/effects) takes -1..1 for the first
// three and degrees for hue.
export const colorEffectDefinition: EffectDefinition = {
	type: "color",
	name: "Color",
	keywords: ["color", "colour", "brightness", "contrast", "saturation", "hue", "correct", "grade"],
	params: [
		{ key: "brightness", label: "Brightness", type: "number", default: 0, min: -100, max: 100, step: 1 },
		{ key: "contrast", label: "Contrast", type: "number", default: 0, min: -100, max: 100, step: 1 },
		{ key: "saturation", label: "Saturation", type: "number", default: 0, min: -100, max: 100, step: 1 },
		{ key: "hue", label: "Hue", type: "number", default: 0, min: -180, max: 180, step: 1 },
	],
	renderer: {
		passes: [
			{
				shader: "color-adjust",
				uniforms: ({ effectParams }) => ({
					u_brightness: num({ params: effectParams, key: "brightness" }) / 100,
					u_contrast: num({ params: effectParams, key: "contrast" }) / 100,
					u_saturation: num({ params: effectParams, key: "saturation" }) / 100,
					u_hue: num({ params: effectParams, key: "hue" }),
				}),
			},
		],
	},
};
