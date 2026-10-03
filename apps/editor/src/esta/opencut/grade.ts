// v2's colour grading (packages/core/src/video/color-grading-engine.ts): colour
// wheels, curves, a loaded .cube LUT and HSL, applied in that order. Each is a
// per-pixel colour mapping, so the whole grade is baked into one 3D LUT that
// the `lut-3d` shader (rust/crates/effects) applies.
type RGB = { r: number; g: number; b: number };
type Point = [number, number];

export type Grade = {
	wheels: { shadows: RGB; midtones: RGB; highlights: RGB; lift: number; gamma: number; gain: number };
	curves: { rgb: Point[]; red: Point[]; green: Point[]; blue: Point[] };
	// Eight hue ranges from red; hue in degrees, saturation and luminance -1..1.
	hsl: { hue: number[]; saturation: number[]; luminance: number[] };
	lutMix: number;
};
export type CurveChannel = keyof Grade["curves"];

const ZERO = { r: 0, g: 0, b: 0 };
const LINE: Point[] = [
	[0, 0],
	[1, 1],
];
export const DEFAULT_GRADE: Grade = {
	wheels: { shadows: ZERO, midtones: ZERO, highlights: ZERO, lift: 0, gamma: 1, gain: 1 },
	curves: { rgb: LINE, red: LINE, green: LINE, blue: LINE },
	hsl: { hue: Array(8).fill(0), saturation: Array(8).fill(0), luminance: Array(8).fill(0) },
	lutMix: 1,
};

// The size every baked and loaded LUT is resampled to: the usual size for
// shipped looks, and small enough to rebake on every slider move.
export const LUT_SIZE = 33;

export function parseGrade(raw: unknown): Grade {
	if (typeof raw !== "string" || !raw) return DEFAULT_GRADE;
	try {
		const g: Partial<Grade> = JSON.parse(raw);
		return {
			wheels: { ...DEFAULT_GRADE.wheels, ...g.wheels },
			curves: { ...DEFAULT_GRADE.curves, ...g.curves },
			hsl: { ...DEFAULT_GRADE.hsl, ...g.hsl },
			lutMix: typeof g.lutMix === "number" ? g.lutMix : 1,
		};
	} catch {
		return DEFAULT_GRADE;
	}
}

const isLine = (points: Point[]) => points.length === 2 && points[0][0] === 0 && points[0][1] === 0 && points[1][0] === 1 && points[1][1] === 1;
const isZero = (c: RGB) => c.r === 0 && c.g === 0 && c.b === 0;

export function isIdentity({ grade, lut }: { grade: Grade; lut: Uint8Array | null }) {
	const w = grade.wheels;
	return (
		!lut &&
		isZero(w.shadows) &&
		isZero(w.midtones) &&
		isZero(w.highlights) &&
		w.lift === 0 &&
		w.gamma === 1 &&
		w.gain === 1 &&
		Object.values(grade.curves).every(isLine) &&
		[...grade.hsl.hue, ...grade.hsl.saturation, ...grade.hsl.luminance].every((v) => v === 0)
	);
}

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const ease = (t: number) => t * t * (3 - 2 * t);


// v2's buildCurveLUT: straight line for two points, Catmull-Rom otherwise.
export function curveTable(points: Point[]) {
	const pts = [...points].sort((a, b) => a[0] - b[0]);
	if (!pts.length || pts[0][0] > 0) pts.unshift([0, 0]);
	if (pts[pts.length - 1][0] < 1) pts.push([1, 1]);
	const table = new Float32Array(256);
	for (let i = 0; i < 256; i++) {
		const x = i / 255;
		let y = x;
		for (let j = 0; j < pts.length - 1; j++) {
			if (x < pts[j][0] || x > pts[j + 1][0]) continue;
			const p0 = pts[Math.max(0, j - 1)];
			const p1 = pts[j];
			const p2 = pts[j + 1];
			const p3 = pts[Math.min(pts.length - 1, j + 2)];
			const t = p2[0] === p1[0] ? 0 : (x - p1[0]) / (p2[0] - p1[0]);
			y =
				pts.length === 2
					? p1[1] + t * (p2[1] - p1[1])
					: 0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t * t + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t * t * t);
			break;
		}
		table[i] = clamp01(y);
	}
	return table;
}

const lookup = (table: Float32Array) => (v: number) => {
	const x = clamp01(v) * 255;
	const i = Math.min(254, Math.floor(x));
	return table[i] + (table[i + 1] - table[i]) * (x - i);
};

function rgbToHsl([r, g, b]: number[]): [number, number, number] {
	const max = Math.max(r, g, b);
	const min = Math.min(r, g, b);
	const l = (max + min) / 2;
	if (max === min) return [0, 0, l];
	const d = max - min;
	const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
	const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
	return [h / 6, s, l];
}

function hue2rgb({ p, q, t }: { p: number; q: number; t: number }) {
	const u = t < 0 ? t + 1 : t > 1 ? t - 1 : t;
	if (u < 1 / 6) return p + (q - p) * 6 * u;
	if (u < 1 / 2) return q;
	if (u < 2 / 3) return p + (q - p) * (2 / 3 - u) * 6;
	return p;
}

function hslToRgb([h, s, l]: number[]): number[] {
	if (s === 0) return [l, l, l];
	const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
	const p = 2 * l - q;
	return [hue2rgb({ p, q, t: h + 1 / 3 }), hue2rgb({ p, q, t: h }), hue2rgb({ p, q, t: h - 1 / 3 })];
}

// Trilinear lookup in a LUT_SIZE cube of 8-bit RGB, red fastest.
// Trilinear lookup in a cube of 8-bit RGB (red fastest), written out flat:
// it runs for every point of every bake.
function sampleCube({ cube, size, rgb, out }: { cube: Uint8Array; size: number; rgb: number[]; out: number[] }) {
	const n = size - 1;
	const pr = clamp01(rgb[0]) * n;
	const pg = clamp01(rgb[1]) * n;
	const pb = clamp01(rgb[2]) * n;
	const ri = Math.min(n - 1, Math.floor(pr));
	const gi = Math.min(n - 1, Math.floor(pg));
	const bi = Math.min(n - 1, Math.floor(pb));
	const fr = pr - ri;
	const fg = pg - gi;
	const fb = pb - bi;
	const o000 = ((bi * size + gi) * size + ri) * 3;
	const dr = 3;
	const dg = size * 3;
	const db = size * size * 3;
	for (let c = 0; c < 3; c++) {
		const o = o000 + c;
		const x00 = cube[o] + (cube[o + dr] - cube[o]) * fr;
		const x10 = cube[o + dg] + (cube[o + dg + dr] - cube[o + dg]) * fr;
		const x01 = cube[o + db] + (cube[o + db + dr] - cube[o + db]) * fr;
		const x11 = cube[o + db + dg] + (cube[o + db + dg + dr] - cube[o + db + dg]) * fr;
		const y0 = x00 + (x10 - x00) * fg;
		const y1 = x01 + (x11 - x01) * fg;
		out[c] = (y0 + (y1 - y0) * fb) / 255;
	}
	return out;
}

// The grade as a LUT_SIZE atlas of RGBA pixels: LUT_SIZE slices of
// LUT_SIZE x LUT_SIZE side by side, x = red + blue * LUT_SIZE, y = green.
export function bakeGrade({ grade, lut }: { grade: Grade; lut: Uint8Array | null }) {
	const { wheels: w, hsl } = grade;
	const curves = { rgb: curveTable(grade.curves.rgb), red: curveTable(grade.curves.red), green: curveTable(grade.curves.green), blue: curveTable(grade.curves.blue) };
	const hueShift = hsl.hue.some((v) => v !== 0) || hsl.saturation.some((v) => v !== 0) || hsl.luminance.some((v) => v !== 0);
	const n = LUT_SIZE;
	const pixels = new Uint8ClampedArray(n * n * n * 4);
	const keys = ["r", "g", "b"] as const;
	const channels = [curves.red, curves.green, curves.blue].map(lookup);
	const master = lookup(curves.rgb);
	const graded = [0, 0, 0];
	let rgb = [0, 0, 0];
	for (let bi = 0; bi < n; bi++)
		for (let gi = 0; gi < n; gi++)
			for (let ri = 0; ri < n; ri++) {
				rgb[0] = ri / (n - 1);
				rgb[1] = gi / (n - 1);
				rgb[2] = bi / (n - 1);
				const luma = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2];
				const sw = 1 - ease(clamp01(luma / 0.5));
				const hw = ease(clamp01((luma - 0.5) / 0.5));
				const mw = 1 - sw - hw;
				for (let c = 0; c < 3; c++) {
					const k = keys[c];
					let x = rgb[c] + w.shadows[k] * sw + w.midtones[k] * mw + w.highlights[k] * hw + w.lift * sw;
					x = Math.max(0, x) ** (1 / w.gamma);
					rgb[c] = master(channels[c](clamp01(x * (1 + (w.gain - 1) * hw))));
				}
				if (lut) {
					sampleCube({ cube: lut, size: LUT_SIZE, rgb, out: graded });
					for (let c = 0; c < 3; c++) rgb[c] += (graded[c] - rgb[c]) * grade.lutMix;
				}
				if (hueShift) {
					const [h, s, l] = rgbToHsl(rgb);
					const range = Math.floor(h * 8) % 8;
					rgb = hslToRgb([(((h + hsl.hue[range] / 360) % 1) + 1) % 1, clamp01(s + hsl.saturation[range]), clamp01(l + hsl.luminance[range])]);
				}
				const o = ((gi * n * n) + bi * n + ri) * 4;
				pixels[o] = Math.round(rgb[0] * 255);
				pixels[o + 1] = Math.round(rgb[1] * 255);
				pixels[o + 2] = Math.round(rgb[2] * 255);
				pixels[o + 3] = 255;
			}
	return pixels;
}

// A .cube file (Adobe/Resolve 3D LUT) resampled to LUT_SIZE, as 8-bit RGB.
export function parseCube(text: string): Uint8Array {
	let size = 0;
	let min = [0, 0, 0];
	let max = [1, 1, 1];
	const values: number[] = [];
	for (const raw of text.split(/\r?\n/)) {
		const line = raw.trim();
		if (!line || line.startsWith("#")) continue;
		const [key, ...rest] = line.split(/\s+/);
		if (key === "LUT_3D_SIZE") size = Number(rest[0]);
		else if (key === "LUT_1D_SIZE") throw new Error("1D LUTs aren't supported; export a 3D .cube");
		else if (key === "DOMAIN_MIN") min = rest.map(Number);
		else if (key === "DOMAIN_MAX") max = rest.map(Number);
		else if (/^[-+.\d]/.test(key)) values.push(Number(key), Number(rest[0]), Number(rest[1]));
	}
	if (size < 2 || values.length !== size ** 3 * 3 || values.some((v) => Number.isNaN(v))) throw new Error("not a 3D .cube LUT");
	const source = new Uint8Array(values.map((v) => Math.round(clamp01(v) * 255)));
	const out = new Uint8Array(LUT_SIZE ** 3 * 3);
	const rgb = [0, 0, 0];
	const graded = [0, 0, 0];
	for (let bi = 0; bi < LUT_SIZE; bi++)
		for (let gi = 0; gi < LUT_SIZE; gi++)
			for (let ri = 0; ri < LUT_SIZE; ri++) {
				// The cube's input domain maps onto 0..1 before sampling.
				rgb[0] = (ri / (LUT_SIZE - 1) - min[0]) / (max[0] - min[0]);
				rgb[1] = (gi / (LUT_SIZE - 1) - min[1]) / (max[1] - min[1]);
				rgb[2] = (bi / (LUT_SIZE - 1) - min[2]) / (max[2] - min[2]);
				sampleCube({ cube: source, size, rgb, out: graded });
				const o = (bi * LUT_SIZE * LUT_SIZE + gi * LUT_SIZE + ri) * 3;
				for (let c = 0; c < 3; c++) out[o + c] = Math.round(graded[c] * 255);
			}
	return out;
}

// The `lut` param holds the file name and the resampled cube: "name|base64".
export const encodeCube = ({ name, cube }: { name: string; cube: Uint8Array }) => `${name.replace(/\|/g, "")}|${btoa(Array.from(cube, (b) => String.fromCharCode(b)).join(""))}`;
export const cubeName = (raw: unknown) => (typeof raw === "string" && raw.includes("|") ? raw.slice(0, raw.indexOf("|")) : null);
export function decodeCube(raw: unknown): Uint8Array | null {
	if (typeof raw !== "string" || !raw.includes("|")) return null;
	const bin = atob(raw.slice(raw.indexOf("|") + 1));
	if (bin.length !== LUT_SIZE ** 3 * 3) return null;
	return Uint8Array.from(bin, (ch) => ch.charCodeAt(0));
}

// Baked LUTs by the effect's own param strings (the loaded LUT, then the
// grade), so a frame that doesn't change the grade reuses the texture. The
// id names the uploaded texture; its pixels never change.
const baked = new Map<string, Map<string, string>>();
const pixelsById = new Map<string, Uint8ClampedArray<ArrayBuffer>>();
const MAX_BAKED = 32;
let nextId = 0;

export function gradeTextureId({ grade, lut }: { grade: string; lut: string }): string | null {
	const known = baked.get(lut)?.get(grade);
	if (known) return known;
	const parsed = parseGrade(grade);
	const cube = decodeCube(lut);
	if (isIdentity({ grade: parsed, lut: cube })) return null;
	const id = `esta-grade-${nextId++}`;
	pixelsById.set(id, bakeGrade({ grade: parsed, lut: cube }));
	baked.set(lut, (baked.get(lut) ?? new Map()).set(grade, id));
	for (const old of pixelsById.keys()) {
		if (pixelsById.size <= MAX_BAKED) break;
		pixelsById.delete(old);
		for (const byGrade of baked.values()) for (const [g, v] of byGrade) if (v === old) byGrade.delete(g);
	}
	return id;
}

export const gradePixels = (id: string) => pixelsById.get(id) ?? null;
