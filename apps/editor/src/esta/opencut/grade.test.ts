import { expect, test } from "bun:test";
import { DEFAULT_GRADE, LUT_SIZE, bakeGrade, decodeCube, encodeCube, gradeTextureId, parseCube } from "./grade";

const N = LUT_SIZE;
const pixel = ({ atlas, r, g, b }: { atlas: Uint8ClampedArray; r: number; g: number; b: number }) => {
	const o = (g * N * N + b * N + r) * 4;
	return [atlas[o], atlas[o + 1], atlas[o + 2]];
};
const cube = ({ size, fn }: { size: number; fn: (rgb: number[]) => number[] }) => {
	const lines = [`LUT_3D_SIZE ${size}`];
	for (let b = 0; b < size; b++) for (let g = 0; g < size; g++) for (let r = 0; r < size; r++) lines.push(fn([r, g, b].map((v) => v / (size - 1))).join(" "));
	return lines.join("\n");
};

test("the default grade bakes to the identity", () => {
	const atlas = bakeGrade({ grade: DEFAULT_GRADE, lut: null });
	for (const [r, g, b] of [[0, 0, 0], [32, 32, 32], [10, 20, 30], [32, 0, 16]]) expect(pixel({ atlas, r, g, b })).toEqual([r, g, b].map((v) => Math.round((v / (N - 1)) * 255)));
});

test("an identity grade needs no pass; a real one gets a stable id", () => {
	expect(gradeTextureId({ grade: "", lut: "" })).toBeNull();
	const grade = JSON.stringify({ ...DEFAULT_GRADE, wheels: { ...DEFAULT_GRADE.wheels, gain: 1.5 } });
	const id = gradeTextureId({ grade, lut: "" });
	expect(id).not.toBeNull();
	expect(gradeTextureId({ grade, lut: "" })).toBe(id);
});

test("a .cube is parsed, resampled and applied", () => {
	const invert = parseCube(cube({ size: 17, fn: (rgb) => rgb.map((v) => 1 - v) }));
	expect(invert.length).toBe(N ** 3 * 3);
	const round = decodeCube(encodeCube({ name: "invert.cube", cube: invert }));
	expect(round).toEqual(invert);
	const atlas = bakeGrade({ grade: DEFAULT_GRADE, lut: invert });
	expect(pixel({ atlas, r: 0, g: 0, b: 0 })).toEqual([255, 255, 255]);
	expect(pixel({ atlas, r: 32, g: 8, b: 16 })).toEqual([0, 191, 128]);
	expect(() => parseCube("LUT_1D_SIZE 4\n0 0 0")).toThrow();
	expect(() => parseCube("LUT_3D_SIZE 3\n0 0 0")).toThrow();
});

test("curves, wheels and HSL move colours the right way", () => {
	const lifted = bakeGrade({ grade: { ...DEFAULT_GRADE, curves: { ...DEFAULT_GRADE.curves, rgb: [[0, 0], [0.5, 0.75], [1, 1]] } }, lut: null });
	expect(pixel({ atlas: lifted, r: 16, g: 16, b: 16 })[0]).toBeGreaterThan(170);
	const warm = bakeGrade({ grade: { ...DEFAULT_GRADE, wheels: { ...DEFAULT_GRADE.wheels, midtones: { r: 0.2, g: -0.05, b: -0.15 } } }, lut: null });
	const [r, , b] = pixel({ atlas: warm, r: 16, g: 16, b: 16 });
	expect(r).toBeGreaterThan(b);
	const hsl = { ...DEFAULT_GRADE.hsl, saturation: [-1, 0, 0, 0, 0, 0, 0, 0] };
	const greyReds = bakeGrade({ grade: { ...DEFAULT_GRADE, hsl }, lut: null });
	const red = pixel({ atlas: greyReds, r: 32, g: 0, b: 0 });
	expect(red[0]).toBe(red[1]);
	expect(pixel({ atlas: greyReds, r: 0, g: 0, b: 32 })).toEqual([0, 0, 255]);
});

test("baking is quick enough to redo on a slider move", () => {
	const grade = { ...DEFAULT_GRADE, hsl: { ...DEFAULT_GRADE.hsl, hue: [10, 0, 0, 0, 0, 0, 0, 0] } };
	const lut = parseCube(cube({ size: 2, fn: (rgb) => rgb }));
	bakeGrade({ grade, lut });
	const t = performance.now();
	bakeGrade({ grade, lut });
	expect(performance.now() - t).toBeLessThan(150);
});
