"use client";

import { useRef, useState } from "react";
import type { EffectPanelProps } from "@/effects/types";
import { type CurveChannel, DEFAULT_GRADE, type Grade, cubeName, curveTable, encodeCube, parseCube, parseGrade } from "./grade";

// The Grade effect's editor: v2's ColorGradingSection (wheels, curves, LUT,
// HSL) over the effect's `grade` and `lut` params.
type Update = ({ next, done }: { next: Grade; done?: boolean }) => void;

const RANGES = [
	{ label: "Reds", color: "#ef4444" },
	{ label: "Oranges", color: "#f97316" },
	{ label: "Yellows", color: "#eab308" },
	{ label: "Greens", color: "#22c55e" },
	{ label: "Cyans", color: "#06b6d4" },
	{ label: "Blues", color: "#3b82f6" },
	{ label: "Purples", color: "#8b5cf6" },
	{ label: "Magentas", color: "#ec4899" },
];
const CHANNELS: { key: CurveChannel; label: string; stroke: string }[] = [
	{ key: "rgb", label: "RGB", stroke: "currentColor" },
	{ key: "red", label: "R", stroke: "#ef4444" },
	{ key: "green", label: "G", stroke: "#22c55e" },
	{ key: "blue", label: "B", stroke: "#3b82f6" },
];

function Slider({ label, value, min, max, step, onChange, onDone }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; onDone: () => void }) {
	return (
		<label className="flex items-center gap-2">
			<span className="text-muted-foreground w-16 shrink-0">{label}</span>
			<input type="range" className="min-w-0 flex-1" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} onPointerUp={onDone} onKeyUp={onDone} />
			<span className="w-10 text-right tabular-nums">{Number(value.toFixed(2))}</span>
		</label>
	);
}

// v2's wheel: x pushes red, up pushes blue, green balances the two.
function Wheel({ label, value, onChange, onDone }: { label: string; value: { r: number; g: number; b: number }; onChange: (v: { r: number; g: number; b: number }) => void; onDone: () => void }) {
	const move = (e: React.PointerEvent<HTMLDivElement>) => {
		const box = e.currentTarget.getBoundingClientRect();
		let x = ((e.clientX - box.left) / box.width) * 2 - 1;
		let y = ((e.clientY - box.top) / box.height) * 2 - 1;
		const d = Math.hypot(x, y);
		if (d > 1) [x, y] = [x / d, y / d];
		const r = x;
		const b = -y;
		onChange({ r, g: -(r + b) / 2, b });
	};
	return (
		<div className="flex flex-col items-center gap-1">
			<div
				role="slider"
				aria-label={`${label} wheel`}
				aria-valuenow={Math.round(Math.hypot(value.r, value.b) * 100)}
				aria-valuetext={`r ${value.r.toFixed(2)}, b ${value.b.toFixed(2)}`}
				tabIndex={0}
				className="relative size-16 cursor-crosshair touch-none rounded-full border"
				style={{ background: "radial-gradient(circle, #808080 0%, transparent 70%), conic-gradient(from 90deg, #f00, #f0f, #00f, #0ff, #0f0, #ff0, #f00)" }}
				onPointerDown={(e) => {
					e.currentTarget.setPointerCapture(e.pointerId);
					move(e);
				}}
				onPointerMove={(e) => e.buttons && move(e)}
				onPointerUp={onDone}
				onDoubleClick={() => {
					onChange({ r: 0, g: 0, b: 0 });
					onDone();
				}}
			>
				<div className="absolute size-2 -translate-1/2 rounded-full border border-black bg-white" style={{ left: `${50 + value.r * 50}%`, top: `${50 - value.b * 50}%` }} />
			</div>
			<span className="text-muted-foreground">{label}</span>
		</div>
	);
}

const SIZE = 160;

function Curves({ grade, update }: { grade: Grade; update: Update }) {
	const [channel, setChannel] = useState<CurveChannel>("rgb");
	const drag = useRef<number | null>(null);
	const points = grade.curves[channel];
	const table = curveTable(points);
	const path = Array.from(table, (y, i) => `${i ? "L" : "M"}${((i / 255) * SIZE).toFixed(1)},${((1 - y) * SIZE).toFixed(1)}`).join("");
	const set = ({ next, done = false }: { next: [number, number][]; done?: boolean }) => update({ next: { ...grade, curves: { ...grade.curves, [channel]: next } }, done });
	const at = (e: React.MouseEvent<SVGSVGElement>) => {
		const box = e.currentTarget.getBoundingClientRect();
		const clamp = (v: number) => Math.min(1, Math.max(0, v));
		return [clamp((e.clientX - box.left) / box.width), clamp(1 - (e.clientY - box.top) / box.height)] as [number, number];
	};
	return (
		<div className="space-y-1">
			<div className="flex gap-1">
				{CHANNELS.map((c) => (
					<button key={c.key} type="button" className={`rounded border px-2 py-0.5 ${channel === c.key ? "bg-accent" : ""}`} onClick={() => setChannel(c.key)}>
						{c.label}
					</button>
				))}
			</div>
			<svg
				role="img"
				aria-label={`${channel} curve`}
				viewBox={`0 0 ${SIZE} ${SIZE}`}
				className="bg-muted w-full max-w-48 touch-none rounded"
				onPointerDown={(e) => {
					e.currentTarget.setPointerCapture(e.pointerId);
					const [x, y] = at(e);
					const hit = points.findIndex((p) => Math.abs(p[0] - x) < 0.04 && Math.abs(p[1] - y) < 0.06);
					if (hit >= 0) {
						drag.current = hit;
						return;
					}
					const next = [...points, [x, y] as [number, number]].sort((a, b) => a[0] - b[0]);
					drag.current = next.findIndex((p) => p[0] === x && p[1] === y);
					set({ next });
				}}
				onPointerMove={(e) => {
					const i = drag.current;
					if (i === null || !e.buttons) return;
					const [x, y] = at(e);
					const lo = i === 0 ? 0 : points[i - 1][0] + 0.01;
					const hi = i === points.length - 1 ? 1 : points[i + 1][0] - 0.01;
					// The end points stay at the edges; only their level moves.
					const px = i === 0 || i === points.length - 1 ? points[i][0] : Math.min(hi, Math.max(lo, x));
					set({ next: points.map((p, j) => (j === i ? [px, y] : p)) });
				}}
				onPointerUp={() => {
					drag.current = null;
					set({ next: points, done: true });
				}}
				onDoubleClick={(e) => {
					const [x, y] = at(e);
					const hit = points.findIndex((p, j) => j > 0 && j < points.length - 1 && Math.abs(p[0] - x) < 0.04 && Math.abs(p[1] - y) < 0.06);
					if (hit >= 0) set({ next: points.filter((_, j) => j !== hit), done: true });
				}}
			>
				{[1, 2, 3].map((k) => (
					<g key={k} stroke="currentColor" strokeOpacity={0.15}>
						<line x1={(k * SIZE) / 4} y1={0} x2={(k * SIZE) / 4} y2={SIZE} />
						<line x1={0} y1={(k * SIZE) / 4} x2={SIZE} y2={(k * SIZE) / 4} />
					</g>
				))}
				<path d={path} fill="none" stroke={CHANNELS.find((c) => c.key === channel)?.stroke} strokeWidth={1.5} />
				{points.map((p) => (
					<circle key={`${p[0]}-${p[1]}`} cx={p[0] * SIZE} cy={(1 - p[1]) * SIZE} r={4} fill="white" stroke="black" />
				))}
			</svg>
			<div className="text-muted-foreground">Click to add a point, drag to move, double-click to remove.</div>
		</div>
	);
}

function Hsl({ grade, update }: { grade: Grade; update: Update }) {
	const [range, setRange] = useState(0);
	const set = ({ key, value }: { key: keyof Grade["hsl"]; value: number }) => update({ next: { ...grade, hsl: { ...grade.hsl, [key]: grade.hsl[key].map((v, i) => (i === range ? value : v)) } } });
	const done = () => update({ next: grade, done: true });
	return (
		<div className="space-y-1">
			<div className="flex gap-1">
				{RANGES.map((r, i) => (
					<button
						key={r.label}
						type="button"
						aria-label={r.label}
						title={r.label}
						className={`size-5 rounded-full border-2 ${i === range ? "border-foreground" : "border-transparent"}`}
						style={{ background: r.color }}
						onClick={() => setRange(i)}
					/>
				))}
			</div>
			<Slider label="Hue" value={grade.hsl.hue[range]} min={-180} max={180} step={1} onChange={(v) => set({ key: "hue", value: v })} onDone={done} />
			<Slider label="Saturation" value={grade.hsl.saturation[range] * 100} min={-100} max={100} step={1} onChange={(v) => set({ key: "saturation", value: v / 100 })} onDone={done} />
			<Slider label="Luminance" value={grade.hsl.luminance[range] * 100} min={-100} max={100} step={1} onChange={(v) => set({ key: "luminance", value: v / 100 })} onDone={done} />
		</div>
	);
}

export function GradePanel({ params, preview, commit }: EffectPanelProps) {
	const grade = parseGrade(params.grade);
	const lutName = cubeName(params.lut);
	const [error, setError] = useState<string | null>(null);
	const update: Update = ({ next, done = false }) => {
		preview({ key: "grade", value: JSON.stringify(next) });
		if (done) commit();
	};
	const done = () => commit();
	const w = grade.wheels;
	const section = "space-y-2 border-t px-4 py-3";

	return (
		<div className="text-xs">
			<details className={section} open>
				<summary className="cursor-pointer font-medium">Color wheels</summary>
				<div className="flex justify-between">
					{(["shadows", "midtones", "highlights"] as const).map((k) => (
						<Wheel key={k} label={k[0].toUpperCase() + k.slice(1)} value={w[k]} onChange={(v) => update({ next: { ...grade, wheels: { ...w, [k]: v } } })} onDone={done} />
					))}
				</div>
				<Slider label="Lift" value={w.lift} min={-1} max={1} step={0.01} onChange={(v) => update({ next: { ...grade, wheels: { ...w, lift: v } } })} onDone={done} />
				<Slider label="Gamma" value={w.gamma} min={0.1} max={4} step={0.01} onChange={(v) => update({ next: { ...grade, wheels: { ...w, gamma: v } } })} onDone={done} />
				<Slider label="Gain" value={w.gain} min={0} max={4} step={0.01} onChange={(v) => update({ next: { ...grade, wheels: { ...w, gain: v } } })} onDone={done} />
			</details>
			<details className={section}>
				<summary className="cursor-pointer font-medium">Curves</summary>
				<Curves grade={grade} update={update} />
			</details>
			<details className={section}>
				<summary className="cursor-pointer font-medium">LUT</summary>
				<div className="flex items-center gap-2">
					<label className="cursor-pointer rounded border px-2 py-0.5">
						Load .cube
						<input
							type="file"
							accept=".cube"
							className="hidden"
							onChange={async (e) => {
								const file = e.target.files?.[0];
								e.target.value = "";
								if (!file) return;
								try {
									preview({ key: "lut", value: encodeCube({ name: file.name, cube: parseCube(await file.text()) }) });
									commit();
									setError(null);
								} catch (err) {
									setError(`${file.name}: ${err instanceof Error ? err.message : String(err)}`);
								}
							}}
						/>
					</label>
					<span className="text-muted-foreground min-w-0 flex-1 truncate">{lutName ?? "None"}</span>
					{lutName && (
						<button type="button" className="rounded border px-2 py-0.5" onClick={() => (preview({ key: "lut", value: "" }), commit())}>
							Clear
						</button>
					)}
				</div>
				{error && <div className="text-destructive">{error}</div>}
				{lutName && <Slider label="Mix" value={grade.lutMix * 100} min={0} max={100} step={1} onChange={(v) => update({ next: { ...grade, lutMix: v / 100 } })} onDone={done} />}
			</details>
			<details className={section}>
				<summary className="cursor-pointer font-medium">HSL</summary>
				<Hsl grade={grade} update={update} />
			</details>
			<div className="border-t px-4 py-3">
				<button type="button" className="rounded border px-2 py-0.5" onClick={() => update({ next: DEFAULT_GRADE, done: true })}>
					Reset grade
				</button>
			</div>
		</div>
	);
}
