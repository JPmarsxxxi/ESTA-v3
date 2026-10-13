"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { EditorCore } from "@/core";
import { useEditor } from "@/editor/use-editor";
import { cn } from "@/utils/ui";
import { post } from "../api";
import { readSelection, selectionBlock, selectionLabel, useTimelineSelection, type SelectedClip } from "../opencut/selection";
import { useWorkspace } from "../store";
import { ChatPanel } from "./chat-panel";
import { PickerPanel } from "./picker-panel";
import { PlannerPanel } from "./planner-panel";

// The controls for whatever is selected on the OpenCut timeline: one plan shot
// gets its plan-editor and picker controls, several clips a list with the
// shared actions, a track its track actions. Empty when nothing is selected.
export function SelectionPanel() {
	const sel = useTimelineSelection();
	const label = selectionLabel(sel);
	if (!label) return <p className="text-muted-foreground p-3 text-xs">Select a clip or a track label on the timeline.</p>;
	if (sel.track) return <TrackControls track={sel.track} count={sel.clips.length} />;
	if (sel.clips.length === 1 && sel.clips[0].shot !== null) return <ShotControls shot={sel.clips[0].shot} />;
	if (sel.clips.length === 1)
		return (
			<p className="text-muted-foreground p-3 text-xs">
				{sel.clips[0].name} is not a plan shot ({sel.clips[0].type}, track {sel.clips[0].track}). Ask Claude about it in the chat.
			</p>
		);
	return <ClipList clips={sel.clips} />;
}

function ShotControls({ shot }: { shot: number }) {
	const { selectedShot, sendChat } = useWorkspace();
	const [tab, setTab] = useState<"plan" | "picker">("picker");
	// ShotSync moves the workspace's shot to the clicked clip; until it has, the
	// panels would show the previous one.
	if (selectedShot !== shot) return null;
	return (
		<div className="flex size-full min-h-0 flex-col">
			<div className="flex shrink-0 items-center gap-1 border-b px-2 py-1 text-xs">
				<span className="mr-1 font-medium">Shot {shot}</span>
				{(["picker", "plan"] as const).map((t) => (
					<button key={t} type="button" onClick={() => setTab(t)} className={cn("rounded px-2 py-0.5", tab === t ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent/60")}>
						{t === "picker" ? "Footage" : "Plan"}
					</button>
				))}
				<Button
					size="sm"
					variant="outline"
					className="ml-auto h-6 text-xs"
					title="Ask Claude to generate this shot (motion graphics or AI video, whichever fits)"
					onClick={() => void sendChat({ text: `Generate a replacement for shot ${shot}: motion graphics or AI video, whichever fits its type.`, selection: selectionBlock(readSelection()) })}
				>
					Generate
				</Button>
			</div>
			<div className="min-h-0 flex-1">{tab === "picker" ? <PickerPanel compact /> : <PlannerPanel compact />}</div>
		</div>
	);
}

function ClipList({ clips }: { clips: SelectedClip[] }) {
	const { session } = useWorkspace();
	const [note, setNote] = useState("");
	const shots = clips.flatMap((c) => (c.shot === null ? [] : [c.shot]));
	const requery = async () => {
		await Promise.all(shots.map((n) => post({ path: "/_plan/api/requery", body: { session, shot_number: n } }).catch(() => {})));
		setNote(`Requery started for shot${shots.length === 1 ? "" : "s"} ${shots.join(", ")}.`);
	};
	const only = (c: SelectedClip) => EditorCore.getInstance().selection.setSelectedElements({ elements: [{ trackId: c.trackId, elementId: c.id }] });
	return (
		<div className="flex size-full min-h-0 flex-col text-xs">
			<div className="flex shrink-0 items-center gap-2 border-b px-2 py-1">
				<span className="font-medium">{clips.length} clips</span>
				{shots.length > 0 && (
					<Button size="sm" variant="outline" className="ml-auto h-6 text-xs" title="New search queries for the plan shots in the selection" onClick={() => void requery()}>
						Requery {shots.length === clips.length ? "all" : `${shots.length} plan shots`}
					</Button>
				)}
			</div>
			<div className="min-h-0 flex-1 overflow-auto">
				{clips.map((c) => (
					<button key={c.id} type="button" onClick={() => only(c)} className="hover:bg-accent/60 flex w-full gap-2 border-b px-2 py-1 text-left">
						<span className="text-muted-foreground w-14 shrink-0">{c.shot !== null ? `shot ${c.shot}` : c.type}</span>
						<span className="min-w-0 flex-1 truncate">{c.media ?? c.name}</span>
						<span className="text-muted-foreground shrink-0">{c.track}</span>
					</button>
				))}
			</div>
			{note && <div className="text-muted-foreground shrink-0 border-t px-2 py-1">{note}</div>}
		</div>
	);
}

function TrackControls({ track, count }: { track: { id: string; name: string; type: string }; count: number }) {
	const editor = useEditor();
	const t = useEditor((e) => e.scenes.getActiveSceneOrNull())?.tracks;
	const live = t ? [...t.overlay, t.main, ...t.audio].find((x) => x.id === track.id) : undefined;
	return (
		<div className="flex flex-wrap items-center gap-2 p-2 text-xs">
			<span className="font-medium">
				Track {track.name} · {count} clips
			</span>
			{live && "muted" in live && (
				<Button size="sm" variant="outline" className="h-6 text-xs" onClick={() => editor.timeline.toggleTrackMute({ trackId: track.id })}>
					{live.muted ? "Unmute" : "Mute"}
				</Button>
			)}
			{live && "hidden" in live && (
				<Button size="sm" variant="outline" className="h-6 text-xs" onClick={() => editor.timeline.toggleTrackVisibility({ trackId: track.id })}>
					{live.hidden ? "Show" : "Hide"}
				</Button>
			)}
		</div>
	);
}

// The simple Edit view's right column: the selection's controls slide in above
// the chat while something is selected.
export function EditChatPanel() {
	const sel = useTimelineSelection();
	const open = Boolean(sel.track || sel.clips.length);
	return (
		<div className="flex size-full min-h-0 flex-col">
			{open && (
				<div className={cn("min-h-0 shrink-0 overflow-hidden border-b", sel.clips.length === 1 && !sel.track ? "h-[55%]" : "max-h-[40%]")}>
					<SelectionPanel />
				</div>
			)}
			<div className="min-h-0 flex-1">
				<ChatPanel />
			</div>
		</div>
	);
}
