import { upsertPathKeyframe } from "@/animation";
import { DEFAULT_BACKGROUND_COLOR } from "@/background/color";
import type { MediaType } from "@/media/types";
import type { TProject } from "@/project/types";
import { CURRENT_PROJECT_VERSION } from "@/services/storage/migrations";
import { IndexedDBAdapter } from "@/services/storage/indexeddb-adapter";
import { storageService } from "@/services/storage/service";
import type { MediaAssetData } from "@/services/storage/types";
import type { AudioElement, AudioTrack, ImageElement, OverlayTrack, TScene, TextElement, TimelineElement, VideoElement, VideoTrack } from "@/timeline";
import { resolveAnimationTarget } from "@/timeline/animation-targets";
import { VOLUME_DB_MAX, VOLUME_DB_MIN } from "@/timeline/audio-constants";
import { DEFAULTS } from "@/timeline/defaults";
import { buildElementFromMedia, buildTextElement } from "@/timeline/element-utils";
import { MAIN_TRACK_NAME } from "@/timeline/placement/main-track";
import { getProjectDurationFromScenes } from "@/timeline/scenes";
import { generateUUID } from "@/utils/id";
import { ZERO_MEDIA_TIME, mediaTimeFromSeconds } from "@/wasm";
import { api } from "../api";

// The intermediate tools/opencut/from_openreel.py writes (served by /_opencut/:id).
type ImportMedia = {
	id: string;
	url: string;
	mediaType: MediaType;
	name: string;
	sourceDuration: number;
	width: number;
	height: number;
	fps: number;
	hasAudio: boolean;
	size?: number;
	mtimeMs?: number;
	missing?: boolean;
};
type ImportKeyframe = { time: number; property: string; value: number };
type ImportVideo = {
	clipId?: string | null;
	mediaId: string;
	kind: "video" | "image";
	name: string;
	startTime: number;
	duration: number;
	inPoint: number;
	outPoint: number;
	sourceDuration: number;
	speed?: number | null;
	keyframes: ImportKeyframe[];
};
type ImportAudio = Omit<ImportVideo, "kind" | "speed" | "keyframes"> & { volume: number };
type ImportText = { startTime: number; duration: number; content: string; params: Record<string, string | number | boolean>; keyframes: ImportKeyframe[] };
type Lane<T> = { name: string; elements: T[]; muted: boolean };

export type EstaImport = {
	project: { id: string; name: string; width: number; height: number; fps: number };
	media: ImportMedia[];
	tracks: {
		main: Lane<ImportVideo> & { transitions: { clipAId: string; clipBId: string; type: string; duration: number }[] };
		overlay: Lane<ImportVideo>[];
		audio: Lane<ImportAudio>[];
	};
	text: ImportText[];
	originals: boolean;
	summary: Record<string, unknown>;
};

export type EmitProgress = { phase: "convert" | "media" | "save"; done: number; total: number; label: string };

export const projectIdFor = (session: string) => `esta-${session}`;

// OpenReel keyframe properties -> OpenCut animation paths. Render only emits
// scale today; the rest are the other properties OpenReel's engine animated.
const KEYFRAME_PATHS: Record<string, string> = {
	"scale.x": "transform.scaleX",
	"scale.y": "transform.scaleY",
	"position.x": "transform.positionX",
	"position.y": "transform.positionY",
	rotation: "transform.rotate",
	opacity: "opacity",
};

const t = (seconds: number) => mediaTimeFromSeconds({ seconds: Math.max(0, seconds) });

function withKeyframes<T extends TimelineElement>({ element, keyframes }: { element: T; keyframes: ImportKeyframe[] }): T {
	let animations = element.animations;
	for (const k of keyframes) {
		const path = KEYFRAME_PATHS[k.property];
		if (!path || typeof k.value !== "number") continue;
		const target = resolveAnimationTarget({ element: { ...element, animations }, path });
		if (!target) continue;
		animations = upsertPathKeyframe({
			animations,
			propertyPath: path,
			time: t(k.time),
			value: k.value,
			interpolation: "linear",
			channelLayout: target.channelLayout,
			coerceValue: target.coerceValue,
		});
	}
	return { ...element, animations };
}

const clampKeyframes = ({ keyframes, duration }: { keyframes: ImportKeyframe[]; duration: number }) =>
	keyframes.map((k) => ({ ...k, time: Math.min(Math.max(k.time, 0), duration) }));

function visualElement({ clip, muted }: { clip: ImportVideo; muted: boolean }): VideoElement | ImageElement {
	const base = buildElementFromMedia({ mediaId: clip.mediaId, mediaType: clip.kind, name: clip.name, duration: t(clip.duration), startTime: t(clip.startTime) });
	const id = clip.clipId || generateUUID();
	const keyframes = clampKeyframes({ keyframes: clip.keyframes, duration: clip.duration });
	if (base.type === "image") return withKeyframes({ element: { ...base, id }, keyframes });
	if (base.type !== "video") throw new Error(`unexpected element type ${base.type}`);
	const rate = clip.speed && clip.speed > 0 ? clip.speed : 1;
	const element: VideoElement = {
		...base,
		id,
		trimStart: t(clip.inPoint),
		// OpenCut's trim is what is cut off each end of the source; OpenReel's is the kept window.
		trimEnd: clip.sourceDuration > 0 ? t(clip.sourceDuration - clip.outPoint) : ZERO_MEDIA_TIME,
		sourceDuration: clip.sourceDuration > 0 ? t(clip.sourceDuration) : base.sourceDuration,
		// Render mutes the video lanes so source audio never competes with the voiceover.
		isSourceAudioEnabled: !muted,
		...(rate !== 1 && { retime: { rate } }),
	};
	return withKeyframes({ element, keyframes });
}

function audioElement(clip: ImportAudio): AudioElement {
	const base = buildElementFromMedia({ mediaId: clip.mediaId, mediaType: "audio", name: clip.name, duration: t(clip.duration), startTime: t(clip.startTime) });
	if (base.type !== "audio" || base.sourceType !== "upload") throw new Error("unexpected audio element");
	// OpenReel volume is linear gain; OpenCut's is dB.
	const db = clip.volume > 0 ? Math.min(VOLUME_DB_MAX, Math.max(VOLUME_DB_MIN, 20 * Math.log10(clip.volume))) : VOLUME_DB_MIN;
	return {
		...base,
		id: clip.clipId || generateUUID(),
		trimStart: t(clip.inPoint),
		trimEnd: clip.sourceDuration > 0 ? t(clip.sourceDuration - clip.outPoint) : ZERO_MEDIA_TIME,
		sourceDuration: clip.sourceDuration > 0 ? t(clip.sourceDuration) : base.sourceDuration,
		params: { ...base.params, volume: db },
	};
}

function textElement({ block, index }: { block: ImportText; index: number }): TextElement {
	const base = buildTextElement({ raw: { name: block.content.slice(0, 40), duration: t(block.duration), params: { ...block.params, content: block.content } }, startTime: t(block.startTime) });
	if (base.type !== "text") throw new Error("unexpected text element");
	return withKeyframes({ element: { ...base, id: `esta-caption-${index}` }, keyframes: clampKeyframes({ keyframes: block.keyframes, duration: block.duration }) });
}

// OpenCut has no transitions, so render's crossfades are realised as v2's spike
// did: alternate clips move to a "Main B" lane above the main track, the earlier
// clip of each pair runs on under/over the cut, and the upper one fades. Cut
// points stay where the plan put them. "Shot N" therefore means main + lanes
// named "Main*", sorted by start time.
function splitCrossfades(main: Lane<ImportVideo> & { transitions: EstaImport["tracks"]["main"]["transitions"] }) {
	const clips = main.elements.map((c) => ({ ...c, keyframes: [...c.keyframes] }));
	const fades = new Map(main.transitions.filter((x) => x.type === "crossfade").map((x) => [`${x.clipAId}|${x.clipBId}`, x.duration]));
	const lanes = { a: [] as ImportVideo[], b: [] as ImportVideo[] };
	const useB = fades.size > 0;
	clips.forEach((clip, i) => {
		(useB && i % 2 === 1 ? lanes.b : lanes.a).push(clip);
		const next = clips[i + 1];
		const d = next && clip.clipId && next.clipId ? fades.get(`${clip.clipId}|${next.clipId}`) : undefined;
		if (!d || !next) return;
		const rate = clip.speed && clip.speed > 0 ? clip.speed : 1;
		const spare = clip.kind === "image" || clip.sourceDuration <= 0 ? d : (clip.sourceDuration - clip.outPoint) / rate;
		const run = Math.min(d, spare);
		if (run < 0.02) return;
		const end = clip.duration;
		clip.duration += run;
		clip.outPoint += run * rate;
		if (i % 2 === 1) clip.keyframes.push({ time: end, property: "opacity", value: 1 }, { time: end + run, property: "opacity", value: 0 });
		else next.keyframes.push({ time: 0, property: "opacity", value: 0 }, { time: run, property: "opacity", value: 1 });
	});
	return lanes;
}

export function buildScene(doc: EstaImport): TScene {
	const present = new Set(doc.media.filter((m) => !m.missing).map((m) => m.id));
	const keep = <T extends { mediaId: string }>(els: T[]) => els.filter((e) => present.has(e.mediaId));
	const main = doc.tracks.main;
	const lanes = splitCrossfades({ ...main, elements: keep(main.elements) });
	const videoTrack = ({ name, clips, muted }: { name: string; clips: ImportVideo[]; muted: boolean }): VideoTrack => ({
		id: generateUUID(),
		name,
		type: "video",
		elements: clips.map((clip) => visualElement({ clip, muted })),
		muted,
		hidden: false,
	});

	// overlay[0] draws on top: captions, then graphics, then the crossfade lane.
	const overlay: OverlayTrack[] = [];
	if (doc.text.length) overlay.push({ id: generateUUID(), name: "Captions", type: "text", elements: doc.text.map((block, index) => textElement({ block, index })), hidden: false });
	for (const lane of doc.tracks.overlay) {
		const els = keep(lane.elements);
		if (els.length) overlay.push(videoTrack({ name: lane.name, clips: els, muted: lane.muted }));
	}
	if (lanes.b.length) overlay.push(videoTrack({ name: "Main B", clips: lanes.b, muted: main.muted }));

	const audio: AudioTrack[] = doc.tracks.audio
		.map((lane) => ({ id: generateUUID(), name: lane.name, type: "audio" as const, elements: keep(lane.elements).map(audioElement), muted: lane.muted }))
		.filter((lane) => lane.elements.length);

	return {
		id: generateUUID(),
		name: "Main scene",
		isMain: true,
		tracks: { overlay, main: videoTrack({ name: MAIN_TRACK_NAME, clips: lanes.a, muted: main.muted }), audio },
		bookmarks: [],
		createdAt: new Date(),
		updatedAt: new Date(),
	};
}

// Media lives in OpenCut's per-project OPFS store. A re-emit only downloads
// files whose size or mtime changed (render reuses media ids across passes),
// and drops what the new revision no longer references.
async function syncMedia({ projectId, media, onProgress }: { projectId: string; media: ImportMedia[]; onProgress: (p: EmitProgress) => void }) {
	const meta = new IndexedDBAdapter<MediaAssetData>({ dbName: `video-editor-media-${projectId}`, storeName: "media-metadata", version: 1 });
	const stored = new Map((await meta.getAll()).map((m) => [m.id, m]));
	const wanted = media.filter((m) => !m.missing);
	let done = 0;
	for (const m of wanted) {
		onProgress({ phase: "media", done, total: wanted.length, label: m.name });
		const have = stored.get(m.id);
		if (!have || have.size !== m.size || have.lastModified !== m.mtimeMs) {
			const res = await fetch(m.url, { cache: "no-store" });
			if (!res.ok) throw new Error(`${m.name}: HTTP ${res.status}`);
			const blob = await res.blob();
			const file = new File([blob], m.url.split("/").pop() || m.name, { type: blob.type, lastModified: m.mtimeMs });
			await storageService.saveMediaAsset({
				projectId,
				mediaAsset: {
					id: m.id,
					name: m.name,
					type: m.mediaType,
					file,
					width: m.width || undefined,
					height: m.height || undefined,
					duration: m.sourceDuration || undefined,
					fps: m.fps || undefined,
					hasAudio: m.hasAudio,
				},
			});
		}
		done++;
	}
	const keepIds = new Set(wanted.map((m) => m.id));
	for (const id of stored.keys()) if (!keepIds.has(id)) await storageService.deleteMediaAsset({ projectId, id });
	onProgress({ phase: "media", done, total: wanted.length, label: "" });
}

export async function emitSession({ session, originals, onProgress = () => {} }: { session: string; originals: boolean; onProgress?: (p: EmitProgress) => void }) {
	onProgress({ phase: "convert", done: 0, total: 1, label: "from_openreel.py" });
	const doc = await api<EstaImport>(`/_opencut/${encodeURIComponent(session)}${originals ? "?originals=1" : ""}`);
	const projectId = projectIdFor(session);
	const scene = buildScene(doc);
	await syncMedia({ projectId, media: doc.media, onProgress });

	onProgress({ phase: "save", done: 0, total: 1, label: "project" });
	const previous = await storageService.loadProject({ id: projectId });
	const project: TProject = {
		metadata: {
			id: projectId,
			name: doc.project.name,
			duration: getProjectDurationFromScenes({ scenes: [scene] }),
			createdAt: previous?.project.metadata.createdAt ?? new Date(),
			updatedAt: new Date(),
		},
		scenes: [scene],
		currentSceneId: scene.id,
		settings: {
			fps: { numerator: doc.project.fps || 30, denominator: 1 },
			canvasSize: { width: doc.project.width, height: doc.project.height },
			canvasSizeMode: "custom",
			lastCustomCanvasSize: null,
			originalCanvasSize: null,
			background: previous?.project.settings.background ?? { type: "color", color: DEFAULT_BACKGROUND_COLOR },
		},
		version: CURRENT_PROJECT_VERSION,
		timelineViewState: previous?.project.timelineViewState ?? DEFAULTS.timeline.viewState,
	};
	await storageService.saveProject({ project });
	onProgress({ phase: "save", done: 1, total: 1, label: "project" });
	const missing = doc.media.filter((m) => m.missing).map((m) => m.url);
	return { projectId, originals: doc.originals, summary: doc.summary, missing };
}
