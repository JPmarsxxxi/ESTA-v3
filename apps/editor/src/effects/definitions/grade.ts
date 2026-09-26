import type { EffectDefinition } from "@/effects/types";
import { GradePanel } from "@/esta/opencut/grade-panel";
import { LUT_SIZE, gradeTextureId } from "@/esta/opencut/grade";

// Colour grading: wheels, curves, a .cube LUT and HSL (esta/opencut/grade.ts),
// baked into one 3D LUT for the "lut-3d" shader. Only Intensity is an
// ordinary field; the grade lives in the `grade` (JSON) and `lut` (base64)
// params that the Grade panel edits.
export const gradeEffectDefinition: EffectDefinition = {
	type: "grade",
	name: "Grade",
	keywords: ["grade", "grading", "lut", "cube", "curves", "wheels", "hsl", "color", "colour", "look"],
	params: [{ key: "intensity", label: "Intensity", type: "number", default: 100, min: 0, max: 100, step: 1 }],
	panel: GradePanel,
	renderer: {
		passes: [],
		buildPasses: ({ effectParams }) => {
			const lut = gradeTextureId({
				grade: typeof effectParams.grade === "string" ? effectParams.grade : "",
				lut: typeof effectParams.lut === "string" ? effectParams.lut : "",
			});
			const intensity = typeof effectParams.intensity === "number" ? effectParams.intensity : 100;
			return lut ? [{ shader: "lut-3d", uniforms: { u_size: LUT_SIZE, u_intensity: intensity / 100 }, lut }] : [];
		},
	},
};
