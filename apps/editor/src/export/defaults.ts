import type { ExportOptions } from "./index";

export const DEFAULT_EXPORT_OPTIONS = {
	format: "mp4",
	// very_high, not high: these exports are finals for a monetised channel, and
	// mediabunny's presets scale with resolution, so the step up costs file size
	// and encode time — not detail we'd have to recover later.
	quality: "very_high",
	includeAudio: true,
} satisfies ExportOptions;
