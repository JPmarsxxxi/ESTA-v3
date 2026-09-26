"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { EditorCore } from "@/core";
import { useEditor } from "@/editor/use-editor";
import type { AudioElement } from "@/timeline";
import { mediaTimeToSeconds } from "@/wasm";
import { hasOwnVolumeKeys, isDucked, stripDuck, voiceRegions, withDuck } from "./ducking";
import { DUCK_PRESETS, duckKeys } from "./ducking-plan";

// Sits under the Audio tab's volume fields for audio clips: dips this clip
// wherever the chosen track has speech.
export function DuckingSection({ element, trackId }: { element: AudioElement; trackId: string }) {
	const tracks = useEditor((e) => e.scenes.getActiveSceneOrNull()?.tracks.audio ?? []);
	const sources = tracks.filter((t) => t.id !== trackId && t.elements.length > 0);
	const [sourceId, setSourceId] = useState<string | null>(null);
	const [presetId, setPresetId] = useState<string>("moderate");
	const [status, setStatus] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);
	const source = sources.find((t) => t.id === sourceId) ?? sources.find((t) => /voice/i.test(t.name)) ?? sources[0];
	const preset = DUCK_PRESETS.find((p) => p.id === presetId) ?? DUCK_PRESETS[1];
	const own = hasOwnVolumeKeys(element);

	const update = (next: AudioElement) => EditorCore.getInstance().timeline.updateElements({ updates: [{ trackId, elementId: element.id, patch: { animations: next.animations } }] });

	const apply = async () => {
		if (!source) return;
		setBusy(true);
		try {
			const editor = EditorCore.getInstance();
			const regions = await voiceRegions({ clips: source.elements, assets: editor.media.getAssets(), threshold: preset.threshold });
			const base = typeof element.params.volume === "number" ? element.params.volume : 0;
			const start = mediaTimeToSeconds({ time: element.startTime });
			const { keys, passages } = duckKeys({ regions, preset, start, duration: mediaTimeToSeconds({ time: element.duration }), base });
			if (!passages) return setStatus(`No speech from ${source.name} under this clip.`);
			update(withDuck({ element, keys }));
			setStatus(`Ducked under ${passages} speech passage${passages === 1 ? "" : "s"} from ${source.name}.`);
		} catch (e) {
			setStatus(`Couldn't read ${source.name}: ${e instanceof Error ? e.message : String(e)}`);
		} finally {
			setBusy(false);
		}
	};

	return (
		<div className="space-y-2 border-t p-4 text-xs">
			<div className="font-medium">Duck under voice</div>
			{sources.length === 0 ? (
				<div className="text-muted-foreground">Needs another audio track with clips to duck under.</div>
			) : (
				<>
					<div className="flex items-center gap-2">
						<label htmlFor="duck-source" className="text-muted-foreground w-12">Under</label>
						<select id="duck-source" className="bg-background min-w-0 flex-1 rounded border px-1 py-0.5" value={source?.id} onChange={(e) => setSourceId(e.target.value)}>
							{sources.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
						</select>
					</div>
					<div className="flex items-center gap-2">
						<label htmlFor="duck-preset" className="text-muted-foreground w-12">Amount</label>
						<select id="duck-preset" className="bg-background min-w-0 flex-1 rounded border px-1 py-0.5" value={preset.id} onChange={(e) => setPresetId(e.target.value)}>
							{DUCK_PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label} ({Math.round(20 * Math.log10(1 - p.reduction))} dB)</option>)}
						</select>
					</div>
					{own ? (
						<div className="text-muted-foreground">This clip has its own volume keyframes; remove them to duck it.</div>
					) : (
						<div className="flex gap-2">
							<Button size="sm" disabled={busy} onClick={() => void apply()}>{busy ? "Listening..." : isDucked(element) ? "Re-apply" : "Apply"}</Button>
							{isDucked(element) && (
								<Button size="sm" variant="outline" disabled={busy} onClick={() => { update(stripDuck(element)); setStatus("Ducking removed."); }}>
									Remove
								</Button>
							)}
						</div>
					)}
				</>
			)}
			{status && <div className="text-muted-foreground">{status}</div>}
		</div>
	);
}
