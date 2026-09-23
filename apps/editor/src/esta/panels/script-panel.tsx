"use client";

import { Plus } from "lucide-react";
import { ConflictBanner, useSessionDoc } from "../doc";
import { useWorkspace } from "../store";
import { LineEditor } from "./line-editor";

// Port of v2 apps/studio WritingStageView: talking points (script_metadata.json)
// and script.md, each as a LineEditor with debounced saves and a conflict guard.

const isScriptHeader = (line: string) => /^\[(HOOK|BODY|CTA)\]\s*$/.test(line.trim());

type Meta = Record<string, unknown> & { talking_points?: unknown };

export function ScriptPanel() {
	const { sendChat } = useWorkspace();
	const script = useSessionDoc<string[]>({
		path: "script.md",
		parse: (t) => t.split("\n"),
		serialize: (lines) => lines.join("\n"),
	});
	// The rest of script_metadata.json is kept intact across talking-point saves.
	const meta = useSessionDoc<Meta>({
		path: "script_metadata.json",
		parse: (t) => JSON.parse(t),
		serialize: (m) => JSON.stringify(m, null, 2),
	});
	const points = Array.isArray(meta.value?.talking_points) ? meta.value.talking_points.map(String) : [];
	const setPoints = (next: string[]) => meta.value && meta.change({ ...meta.value, talking_points: next, user_edited_talking_points: true });

	return (
		<div className="space-y-5 p-3 text-sm">
			<section className="space-y-1.5">
				<h3 className="text-muted-foreground text-[11px] uppercase">Talking points</h3>
				{meta.conflict && <ConflictBanner what="The talking points" onResolve={meta.resolve} />}
				{meta.missing ? (
					<p className="text-muted-foreground text-xs">No script_metadata.json yet.</p>
				) : meta.value === null ? (
					<p className="text-muted-foreground text-xs">Loading…</p>
				) : (
					<>
						{points.length === 0 ? (
							<p className="text-muted-foreground text-xs">No talking points recorded.</p>
						) : (
							<LineEditor lines={points} onChange={setPoints} onInstruct={(t) => void sendChat(`Edit the talking points (script_metadata.json). ${t}`)} showBlanks={false} saving={meta.saving} />
						)}
						<button type="button" onClick={() => setPoints([...points, ""])} className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-[11px]">
							<Plus size={11} /> add point
						</button>
					</>
				)}
			</section>
			<section className="space-y-1.5">
				<h3 className="text-muted-foreground text-[11px] uppercase">Script</h3>
				{script.conflict && <ConflictBanner what="script.md" onResolve={script.resolve} />}
				{script.missing ? (
					<p className="text-muted-foreground text-xs">No script.md yet: draft it from the Stage panel or in chat.</p>
				) : script.value === null ? (
					<p className="text-muted-foreground text-xs">Loading…</p>
				) : (
					<>
						<LineEditor
							lines={script.value}
							onChange={script.change}
							onInstruct={(t) => void sendChat(`Edit the script (script.md). ${t}`)}
							isHeader={isScriptHeader}
							saving={script.saving}
						/>
						<button type="button" onClick={() => script.value && script.change([...script.value, ""])} className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-[11px]">
							<Plus size={11} /> add line
						</button>
					</>
				)}
			</section>
			<p className="text-muted-foreground text-[10px]">Edits save to disk as you go. If the script changes after plan or assets ran, re-run them to pick it up.</p>
		</div>
	);
}
