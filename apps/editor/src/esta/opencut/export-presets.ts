import type { ExportOptions } from "@/export";
import { floatToFrameRate } from "@/fps/utils";

// v2's export presets (apps/web/src/services/export-presets.ts), the ones a
// browser can encode: MP4 (H.264) and WebM (VP9). The ProRes, H.265 and MOV
// masters are left out. Bitrates are kbps. v2's per-platform maximum durations
// are left out too: the platforms have raised them since.
export const EXPORT_PRESETS = [
	{ id: "youtube-4k", name: "YouTube 4K", group: "YouTube", format: "mp4", width: 3840, height: 2160, fps: 30, video: 50000, audio: 384 },
	{ id: "youtube-4k-60", name: "YouTube 4K 60fps", group: "YouTube", format: "mp4", width: 3840, height: 2160, fps: 60, video: 65000, audio: 384 },
	{ id: "youtube-1080p", name: "YouTube 1080p HD", group: "YouTube", format: "mp4", width: 1920, height: 1080, fps: 30, video: 8000, audio: 256 },
	{ id: "youtube-shorts", name: "YouTube Shorts", group: "YouTube", format: "mp4", width: 1080, height: 1920, fps: 60, video: 12000, audio: 256 },
	{ id: "tiktok", name: "TikTok", group: "TikTok", format: "mp4", width: 1080, height: 1920, fps: 60, video: 10000, audio: 256 },
	{ id: "instagram-reels", name: "Instagram Reels", group: "Instagram", format: "mp4", width: 1080, height: 1920, fps: 30, video: 8000, audio: 256 },
	{ id: "instagram-feed", name: "Instagram Feed Video", group: "Instagram", format: "mp4", width: 1080, height: 1080, fps: 30, video: 6000, audio: 192 },
	{ id: "instagram-story", name: "Instagram Story", group: "Instagram", format: "mp4", width: 1080, height: 1920, fps: 30, video: 6000, audio: 192 },
	{ id: "twitter", name: "Twitter/X", group: "Social", format: "mp4", width: 1920, height: 1080, fps: 30, video: 8000, audio: 192 },
	{ id: "facebook-feed", name: "Facebook Feed", group: "Social", format: "mp4", width: 1920, height: 1080, fps: 30, video: 8000, audio: 192 },
	{ id: "linkedin", name: "LinkedIn", group: "Social", format: "mp4", width: 1920, height: 1080, fps: 30, video: 8000, audio: 192 },
	{ id: "web-hd", name: "Web HD", group: "Web", format: "mp4", width: 1920, height: 1080, fps: 30, video: 5000, audio: 192 },
	{ id: "web-small", name: "Web Optimized", group: "Web", format: "mp4", width: 1280, height: 720, fps: 30, video: 2500, audio: 128 },
	{ id: "webm-vp9", name: "WebM VP9", group: "Web", format: "webm", width: 1280, height: 720, fps: 30, video: 3000, audio: 128 },
	{ id: "broadcast-1080p-high", name: "1080p High Quality", group: "Master", format: "mp4", width: 1920, height: 1080, fps: 30, video: 20000, audio: 320 },
	{ id: "broadcast-4k", name: "4K UHD Master", group: "Master", format: "mp4", width: 3840, height: 2160, fps: 30, video: 50000, audio: 320 },
] as const;
export type ExportPreset = (typeof EXPORT_PRESETS)[number];

// A preset only fits a project of the same shape; the frame is scaled, never cropped.
export const presetsFor = ({ width, height }: { width: number; height: number }) =>
	EXPORT_PRESETS.filter((p) => Math.abs(p.width / p.height - width / height) < 0.01);

export const presetOptions = (p: ExportPreset): Omit<ExportOptions, "quality" | "includeAudio"> => ({
	format: p.format,
	fps: floatToFrameRate(p.fps),
	width: p.width,
	height: p.height,
	videoBitrate: p.video * 1000,
	audioBitrate: p.audio * 1000,
});
