import { upsertPathKeyframe } from "@/animation";
import { DEFAULT_BACKGROUND_COLOR } from "@/background/color";
import { processMediaAssets } from "@/media/processing";
import type { ParamValues } from "@/params";
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
import { planTransition } from "./transitions";

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
type ImportKeyframe = { time: number; property: string; value: number; id?: string };
// OpenReel's clip transform: position in fractions of the frame from centre,
// scale relative to the fitted size, fitted by "cover" (fill) or "contain".
type ImportTransform = { position?: { x: number; y: number }; scale?: { x: number; y: number }; rotation?: number; opacity?: number; fitMode?: string };
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
	transform?: ImportTransform | null;
};
type ImportAudio = Omit<ImportVideo, "kind" | "speed" | "keyframes"> & { volume: number };
type ImportText = { startTime: number; duration: number; content: string; params: Record<string, string | number | boolean>; keyframes: ImportKeyframe[] };
type Lane<T> = { name: string; elements: T[]; muted: boolean };
// A stream-pending shot of render's early pass; url is set once its asset landed.
type Pending = { clipId: string; shot: number; track: string; name: string; startTime: number; duration: number; transform?: ImportTransform | null; url?: string; mediaType?: "video" | "image"; inPoint?: number; size?: number; mtimeMs?: number };
type MediaInfo = { duration: number; width: number; height: number };
type Canvas = { width: number; height: number };

export type EstaImport = {
	project: { id: string; name: string; width: number; height: number; fps: number };
	media: ImportMedia[];
	tracks: {
		main: Lane<ImportVideo> & { transitions: { clipAId: string; clipBId: string; type: string; duration: number }[] };
		overlay: Lane<ImportVideo>[];
		audio: Lane<ImportAudio>[];
	};
	text: ImportText[];
	pending: Pending[];
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
	"transform.positionX": "transform.positionX",
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
			keyframeId: k.id,
			channelLayout: target.channelLayout,
			coerceValue: target.coerceValue,
		});
	}
	return { ...element, animations };
}

const clampKeyframes = ({ keyframes, duration }: { keyframes: ImportKeyframe[]; duration: number }) =>
	keyframes.map((k) => ({ ...k, time: Math.min(Math.max(k.time, 0), duration) }));

// OpenCut draws a clip at scale 1 fitted inside the canvas ("contain") and
// positions it in pixels from centre. Render fills the frame ("cover") unless a
// composite panel asks for contain, so cover becomes a scale factor from the
// clip's real aspect, applied to render's scale keyframes (Ken Burns, zoom) too.
function placement({ clip, canvas, media }: { clip: ImportVideo; canvas: Canvas; media?: MediaInfo }): { fit: number; params: ParamValues } {
	const tr = clip.transform;
	if (!tr) return { fit: 1, params: {} };
	const fx = media?.width ? canvas.width / media.width : 0;
	const fy = media?.height ? canvas.height / media.height : 0;
	const fit = tr.fitMode === "contain" || !fx || !fy ? 1 : Math.max(fx, fy) / Math.min(fx, fy);
	return {
		fit,
		params: {
			"transform.positionX": Math.round((tr.position?.x ?? 0) * canvas.width),
			"transform.positionY": Math.round((tr.position?.y ?? 0) * canvas.height),
			"transform.scaleX": (tr.scale?.x ?? 1) * fit,
			"transform.scaleY": (tr.scale?.y ?? 1) * fit,
			"transform.rotate": tr.rotation ?? 0,
			opacity: tr.opacity ?? 1,
		},
	};
}

function visualElement({ clip, muted, canvas, media }: { clip: ImportVideo; muted: boolean; canvas: Canvas; media?: MediaInfo }): VideoElement | ImageElement {
	const base = buildElementFromMedia({ mediaId: clip.mediaId, mediaType: clip.kind, name: clip.name, duration: t(clip.duration), startTime: t(clip.startTime) });
	const { fit, params } = placement({ clip, canvas, media });
	const id = clip.clipId || generateUUID();
	const keyframes = clampKeyframes({ keyframes: clip.keyframes, duration: clip.duration }).map((k) =>
		k.property.startsWith("scale.")
			? { ...k, value: k.value * fit }
			: k.property === "position.x"
				? { ...k, value: k.value * canvas.width }
				: k.property === "position.y"
					? { ...k, value: k.value * canvas.height }
					: k,
	);
	if (base.type === "image") {
		const image: ImageElement = { ...base, id, params: { ...base.params, ...params } };
		return withKeyframes({ element: image, keyframes });
	}
	if (base.type !== "video") throw new Error(`unexpected element type ${base.type}`);
	const rate = clip.speed && clip.speed > 0 ? clip.speed : 1;
	const element: VideoElement = {
		...base,
		id,
		params: { ...base.params, ...params },
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
		const plan = planTransition({
			type: "crossfade",
			duration: d,
			a: { duration: clip.duration, spare, top: i % 2 === 1, baseX: 0 },
			b: { duration: next.duration, spare: 0, top: (i + 1) % 2 === 1, baseX: 0 },
			width: 0,
		});
		if (!plan) return;
		clip.duration += plan.run;
		clip.outPoint += plan.run * rate;
		clip.keyframes.push(...plan.out);
		next.keyframes.push(...plan.in);
	});
	return lanes;
}

const placeholderId = (shot: number) => `esta-pending-${shot}`;

// Pending shots whose asset has landed become real media under render's own id,
// so the final render pass reuses the download; the rest get a placeholder card.
function pendingMedia(doc: EstaImport): ImportMedia[] {
	return doc.pending.map((p) =>
		p.url
			? { id: `media-shot-${p.shot}`, url: p.url, mediaType: p.mediaType ?? "video", name: p.name || `Shot ${p.shot}`, sourceDuration: 0, width: 0, height: 0, fps: 0, hasAudio: false, size: p.size, mtimeMs: p.mtimeMs }
			: { id: placeholderId(p.shot), url: "", mediaType: "image", name: `Shot ${p.shot}: fetching`, sourceDuration: 0, width: doc.project.width, height: doc.project.height, fps: 0, hasAudio: false },
	);
}

function pendingClip({ p, info }: { p: Pending; info: Map<string, MediaInfo> }): ImportVideo {
	const base = { clipId: p.clipId, startTime: p.startTime, duration: p.duration, keyframes: [], transform: p.transform };
	if (!p.url) return { ...base, mediaId: placeholderId(p.shot), kind: "image", name: `Shot ${p.shot}: fetching`, inPoint: 0, outPoint: p.duration, sourceDuration: 0 };
	const mediaId = `media-shot-${p.shot}`;
	const src = info.get(mediaId)?.duration ?? 0;
	const inPoint = p.inPoint ?? 0;
	if (p.mediaType !== "video") return { ...base, mediaId, kind: "image", name: p.name, inPoint: 0, outPoint: p.duration, sourceDuration: 0 };
	return { ...base, mediaId, kind: "video", name: p.name, inPoint, outPoint: src > 0 ? Math.min(inPoint + p.duration, src) : inPoint + p.duration, sourceDuration: src };
}

export function buildScene({ doc, info }: { doc: EstaImport; info: Map<string, MediaInfo> }): TScene {
	const present = new Set(info.keys());
	const keep = <T extends { mediaId: string }>(els: T[]) => els.filter((e) => present.has(e.mediaId));
	const pending = doc.pending.map((p) => ({ track: p.track, clip: pendingClip({ p, info }) })).filter((x) => present.has(x.clip.mediaId));
	const withPending = ({ name, els }: { name: string; els: ImportVideo[] }) =>
		[...keep(els), ...pending.filter((x) => x.track === name).map((x) => x.clip)].sort((a, b) => a.startTime - b.startTime);
	const main = doc.tracks.main;
	const lanes = splitCrossfades({ ...main, elements: withPending({ name: "Main", els: main.elements }) });
	const videoTrack = ({ name, clips, muted }: { name: string; clips: ImportVideo[]; muted: boolean }): VideoTrack => ({
		id: generateUUID(),
		name,
		type: "video",
		elements: clips.map((clip) => visualElement({ clip, muted, canvas: doc.project, media: info.get(clip.mediaId) })),
		muted,
		hidden: false,
	});

	// overlay[0] draws on top: captions, then graphics, then the crossfade lane.
	const overlay: OverlayTrack[] = [];
	if (doc.text.length) overlay.push({ id: generateUUID(), name: "Captions", type: "text", elements: doc.text.map((block, index) => textElement({ block, index })), hidden: false });
	const overlayLanes = [...doc.tracks.overlay];
	for (const name of new Set(pending.map((x) => x.track)))
		if (name !== "Main" && !overlayLanes.some((l) => l.name === name)) overlayLanes.push({ name, elements: [], muted: true });
	for (const lane of overlayLanes) {
		const els = withPending({ name: lane.name, els: lane.elements });
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

async function placeholderFile({ media }: { media: ImportMedia }) {
	const canvas = new OffscreenCanvas(Math.round(media.width / 2) || 540, Math.round(media.height / 2) || 960);
	const ctx = canvas.getContext("2d");
	if (!ctx) throw new Error("no 2d canvas");
	ctx.fillStyle = "#26262b";
	ctx.fillRect(0, 0, canvas.width, canvas.height);
	ctx.fillStyle = "#a1a1aa";
	ctx.textAlign = "center";
	ctx.font = `600 ${Math.round(canvas.width / 9)}px sans-serif`;
	ctx.fillText(media.name.replace(/:.*/, ""), canvas.width / 2, canvas.height / 2);
	ctx.font = `${Math.round(canvas.width / 16)}px sans-serif`;
	ctx.fillText("fetching...", canvas.width / 2, canvas.height / 2 + canvas.width / 8);
	return new File([await canvas.convertToBlob({ type: "image/png" })], `${media.id}.png`, { type: "image/png" });
}

// Media lives in OpenCut's per-project OPFS store. A re-emit only downloads
// files whose size or mtime changed (render reuses media ids across passes),
// and drops what the new revision no longer references. Downloads go through
// OpenCut's own upload probe for thumbnails and, for shots hydrated from the
// asset feed, the source duration render hasn't ffprobed yet.
async function syncMedia({ projectId, media, onProgress }: { projectId: string; media: ImportMedia[]; onProgress: (p: EmitProgress) => void }) {
	const meta = new IndexedDBAdapter<MediaAssetData>({ dbName: `video-editor-media-${projectId}`, storeName: "media-metadata", version: 1 });
	const stored = new Map((await meta.getAll()).map((m) => [m.id, m]));
	const wanted = media.filter((m) => !m.missing);
	const info = new Map<string, MediaInfo>();
	let done = 0;
	for (const m of wanted) {
		onProgress({ phase: "media", done, total: wanted.length, label: m.name });
		const have = stored.get(m.id);
		const fresh = m.url ? have && have.size === m.size && have.lastModified === m.mtimeMs : have;
		if (have && fresh) {
			info.set(m.id, { duration: m.sourceDuration || have.duration || 0, width: m.width || have.width || 0, height: m.height || have.height || 0 });
		} else {
			let file: File;
			if (m.url) {
				const res = await fetch(m.url, { cache: "no-store" });
				if (!res.ok) throw new Error(`${m.name}: HTTP ${res.status}`);
				const blob = await res.blob();
				file = new File([blob], m.url.split("/").pop() || m.name, { type: blob.type, lastModified: m.mtimeMs });
			} else {
				file = await placeholderFile({ media: m });
			}
			const [probe] = await processMediaAssets({ files: [file] });
			if (probe?.url) URL.revokeObjectURL(probe.url);
			const duration = m.sourceDuration || probe?.duration || 0;
			await storageService.saveMediaAsset({
				projectId,
				mediaAsset: {
					id: m.id,
					name: m.name,
					type: m.mediaType,
					file,
					width: m.width || probe?.width,
					height: m.height || probe?.height,
					duration: duration || undefined,
					fps: m.fps || probe?.fps,
					hasAudio: m.hasAudio || probe?.hasAudio,
					thumbnailUrl: probe?.thumbnailUrl,
				},
			});
			info.set(m.id, { duration, width: m.width || probe?.width || 0, height: m.height || probe?.height || 0 });
		}
		done++;
	}
	for (const id of stored.keys()) if (!info.has(id)) await storageService.deleteMediaAsset({ projectId, id });
	onProgress({ phase: "media", done, total: wanted.length, label: "" });
	return info;
}

export async function emitSession({ session, originals, onProgress = () => {} }: { session: string; originals: boolean; onProgress?: (p: EmitProgress) => void }) {
	onProgress({ phase: "convert", done: 0, total: 1, label: "from_openreel.py" });
	const doc = await api<EstaImport>(`/_opencut/${encodeURIComponent(session)}${originals ? "?originals=1" : ""}`);
	const projectId = projectIdFor(session);
	const info = await syncMedia({ projectId, media: [...doc.media, ...pendingMedia(doc)], onProgress });
	const scene = buildScene({ doc, info });

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
	// What export must refuse: OpenCut encodes whatever the timeline references.
	const proxied = [...doc.media, ...pendingMedia(doc)].filter((m) => !m.missing && m.url.includes("/assets/proxies/")).map((m) => m.id);
	const hydrated = doc.pending.filter((p) => p.url).length;
	return { projectId, originals: doc.originals, summary: { ...doc.summary, pending: doc.pending.length - hydrated, hydrated }, missing, proxied };
}
