"use client";

import { Section, SectionContent, SectionHeader, SectionTitle } from "@/components/section";
import { type ExportPreset, presetsFor } from "./export-presets";

// Top of OpenCut's export popover. "Project settings" keeps OpenCut's own
// format and quality choices; a preset replaces them with its size, fps and bitrates.
export function ExportPresetSection({ canvas, preset, onChange }: { canvas: { width: number; height: number }; preset: ExportPreset | null; onChange: (preset: ExportPreset | null) => void }) {
	const presets = presetsFor(canvas);
	return (
		<Section showTopBorder={false}>
			<SectionHeader>
				<SectionTitle>Preset</SectionTitle>
			</SectionHeader>
			<SectionContent className="space-y-1 text-xs">
				<select
					aria-label="Export preset"
					className="bg-background w-full rounded border px-1 py-1"
					value={preset?.id ?? ""}
					onChange={(e) => onChange(presets.find((p) => p.id === e.target.value) ?? null)}
				>
					<option value="">
						Project settings ({canvas.width}x{canvas.height})
					</option>
					{presets.map((p) => (
						<option key={p.id} value={p.id}>
							{p.name}
						</option>
					))}
				</select>
				<div className="text-muted-foreground">
					{preset
						? `${preset.width}x${preset.height}, ${preset.fps} fps, ${preset.video / 1000} Mbps ${preset.format === "webm" ? "WebM (VP9)" : "MP4 (H.264)"}, audio ${preset.audio} kbps`
						: presets.length
							? `${presets.length} platform presets fit this ${canvas.width}x${canvas.height} project.`
							: "No platform preset has this project's shape."}
				</div>
			</SectionContent>
		</Section>
	);
}
