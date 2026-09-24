"use client";

import { Fragment, useState, type ComponentType } from "react";
import Link from "next/link";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/ui";
import { WorkspaceProvider, useWorkspace } from "./store";
import { useEventsConnected } from "./events";
import { BadgeDot, PanelShell, badgeLabel } from "./ui";
import { StagePanel } from "./panels/stage-panel";
import { JobsPanel } from "./panels/jobs-panel";
import { ChatPanel } from "./panels/chat-panel";
import { FilesPanel } from "./panels/files-panel";
import { PipelinePanel } from "./panels/pipeline-panel";
import { PlannerPanel } from "./panels/planner-panel";
import { PickerPanel } from "./panels/picker-panel";
import { ScriptPanel } from "./panels/script-panel";
import { RequirementsPanel } from "./panels/requirements-panel";
import { TaggedPanel } from "./panels/tagged-panel";
import { PreviewPanel, TimelinePanel } from "./panels/shots-panels";
import { EditorPanel } from "./panels/editor-panel";
import { OcAssetsPanel, OcPreviewPanel, OcPropertiesPanel, OcTimelinePanel } from "./panels/opencut-panels";
import { OpenCutHost } from "./opencut/host";

export const PANELS: Record<string, { title: string; Component: ComponentType }> = {
	stage: { title: "Stage", Component: StagePanel },
	jobs: { title: "Jobs", Component: JobsPanel },
	chat: { title: "Chat", Component: ChatPanel },
	files: { title: "Files", Component: FilesPanel },
	pipeline: { title: "Pipeline", Component: PipelinePanel },
	requirements: { title: "Requirements", Component: RequirementsPanel },
	script: { title: "Script", Component: ScriptPanel },
	tagged: { title: "Tagged script", Component: TaggedPanel },
	planner: { title: "Plan editor", Component: PlannerPanel },
	picker: { title: "Shot picker", Component: PickerPanel },
	timeline: { title: "Shot strip", Component: TimelinePanel },
	preview: { title: "Shot preview", Component: PreviewPanel },
	editor: { title: "Editor project", Component: EditorPanel },
	"oc-preview": { title: "Editor preview", Component: OcPreviewPanel },
	"oc-timeline": { title: "Editor timeline", Component: OcTimelinePanel },
	"oc-assets": { title: "Editor media", Component: OcAssetsPanel },
	"oc-properties": { title: "Editor properties", Component: OcPropertiesPanel },
};

// A workspace is columns of stacked panels. Each stage has a preset; the user
// can swap which panel sits in which slot and resize, and both persist per stage.
type Layout = string[][];

const PRESETS: Record<string, Layout> = {
	requirements: [["stage", "pipeline"], ["requirements"], ["chat"]],
	"voice-profile": [["stage", "jobs"], ["files"], ["chat"]],
	research: [["stage", "jobs"], ["files"], ["chat"]],
	script: [["stage", "jobs"], ["script"], ["files", "chat"]],
	voice: [["stage", "jobs"], ["tagged"], ["chat"]],
	timestamps: [["stage", "jobs"], ["files"], ["chat"]],
	style: [["stage", "jobs"], ["files"], ["chat"]],
	plan: [["stage", "jobs"], ["planner"], ["preview", "timeline", "chat"]],
	assets: [["stage", "jobs"], ["picker"], ["preview", "chat"]],
	edit: [["stage", "editor", "jobs"], ["oc-preview", "oc-timeline"], ["oc-properties", "oc-assets", "chat"]],
};

const layoutKey = (stage: string) => `esta.layout.${stage}`;

// The stage column is narrow, the surface in the middle gets the room.
function columnSize({ index, count }: { index: number; count: number }) {
	if (count === 1) return 100;
	if (count === 2) return index === 0 ? 34 : 66;
	if (index === 0) return 26;
	if (index === count - 1) return 26;
	return (100 - 52) / (count - 2);
}

function loadLayout(stage: string): Layout {
	const preset = PRESETS[stage] ?? PRESETS.research;
	try {
		const saved: unknown = JSON.parse(localStorage.getItem(layoutKey(stage)) || "null");
		const valid =
			Array.isArray(saved) &&
			saved.length === preset.length &&
			saved.every((col, i) => Array.isArray(col) && col.length === preset[i].length && col.every((p) => typeof p === "string" && p in PANELS));
		if (valid) return saved;
	} catch {
		/* fall through to the preset */
	}
	return preset;
}

export function EstaWorkspace({ session }: { session: string }) {
	return (
		<WorkspaceProvider session={session}>
			<OpenCutHost>
				<Shell />
			</OpenCutHost>
		</WorkspaceProvider>
	);
}

function Shell() {
	const { session, pipeline, pipelineError, stage } = useWorkspace();
	const connected = useEventsConnected();
	return (
		<div className="bg-background text-foreground flex h-screen w-screen flex-col overflow-hidden">
			<header className="flex h-11 shrink-0 items-center justify-between gap-4 border-b px-3 text-sm">
				<div className="flex min-w-0 items-center gap-3">
					<Link href="/" className="text-muted-foreground hover:text-foreground">
						ESTA
					</Link>
					<span className="text-muted-foreground">/</span>
					<span className="truncate font-medium">{pipeline?.requirements?.topic || session}</span>
					{pipeline && <span className="text-muted-foreground truncate text-xs">{pipeline.template ?? "no pipeline.json (canonical order)"}</span>}
				</div>
				<div className="flex items-center gap-2 text-xs">
					<span className={cn("size-2 rounded-full", connected ? "bg-constructive" : "bg-destructive")} />
					<span className="text-muted-foreground">{connected ? "live" : "backend offline"}</span>
				</div>
			</header>
			{pipeline && !pipeline.preflight.esta && (
				<div className="bg-caution/15 border-b px-3 py-1.5 text-xs">
					The <strong>esta</strong> conda env is missing: Python stages are blocked. Run <code>.\setup.ps1</code> once, then reload.
				</div>
			)}
			<div className="flex min-h-0 flex-1">
				<StageRail />
				<main className="min-w-0 flex-1 p-1.5">
					{pipelineError && <div className="p-4 text-sm">Could not load session: {pipelineError}</div>}
					{pipeline && stage && <Workspace key={stage} stage={stage} />}
				</main>
			</div>
		</div>
	);
}

function StageRail() {
	const { pipeline, stage, setStage } = useWorkspace();
	return (
		<nav className="flex w-48 shrink-0 flex-col gap-0.5 border-r p-1.5">
			{pipeline?.stages.map((s, i) => (
				<button
					key={s.id}
					type="button"
					onClick={() => setStage(s.id)}
					title={`${s.label}: ${badgeLabel(s.badge)}${s.locked ? ` (${[...s.missing.map((m) => `needs ${m}`), ...s.pendingApprovals.map((p) => `approve ${p}`)].join(", ")})` : ""}`}
					className={cn(
						"flex items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm",
						s.id === stage ? "bg-accent font-medium" : "hover:bg-accent/60",
						!s.inFlow && "opacity-45",
					)}
				>
					<span className="text-muted-foreground w-4 text-right text-xs tabular-nums">{i + 1}</span>
					<BadgeDot badge={s.badge} />
					<span className="min-w-0 flex-1 truncate">{s.label}</span>
					{s.isNext && <span className="bg-primary text-primary-foreground rounded px-1 text-[10px]">next</span>}
				</button>
			))}
		</nav>
	);
}

function Workspace({ stage }: { stage: string }) {
	const [layout, setLayout] = useState<Layout>(() => loadLayout(stage));
	const [version, setVersion] = useState(0);

	const save = (next: Layout) => {
		setLayout(next);
		try {
			localStorage.setItem(layoutKey(stage), JSON.stringify(next));
		} catch {
			/* layout just won't persist */
		}
	};

	// Choosing a panel that is already shown elsewhere swaps the two slots.
	const assign = ({ col, row, panel }: { col: number; row: number; panel: string }) => {
		const next = layout.map((c) => [...c]);
		const current = next[col][row];
		for (const c of next) for (let r = 0; r < c.length; r++) if (c[r] === panel) c[r] = current;
		next[col][row] = panel;
		save(next);
	};

	const reset = () => {
		try {
			localStorage.removeItem(layoutKey(stage));
			for (const k of Object.keys(localStorage)) if (k.startsWith(`react-resizable-panels:esta-${stage}`)) localStorage.removeItem(k);
		} catch {
			/* nothing persisted */
		}
		setLayout(PRESETS[stage] ?? PRESETS.research);
		setVersion((v) => v + 1);
	};

	return (
		<ResizablePanelGroup key={version} direction="horizontal" autoSaveId={`esta-${stage}-cols`} className="gap-1">
			{layout.map((col, ci) => (
				<Fragment key={ci}>
					{ci > 0 && <ResizableHandle />}
					<ResizablePanel minSize={12} defaultSize={columnSize({ index: ci, count: layout.length })}>
						<ResizablePanelGroup direction="vertical" autoSaveId={`esta-${stage}-col${ci}`} className="gap-1">
							{col.map((panel, ri) => {
								const def = PANELS[panel];
								return (
									<Fragment key={ri}>
										{ri > 0 && <ResizableHandle />}
										<ResizablePanel minSize={10} defaultSize={100 / col.length}>
											<PanelShell
												title={
													<select
														aria-label="Panel in this slot"
														className="bg-transparent text-sm font-medium"
														value={panel}
														onChange={(e) => assign({ col: ci, row: ri, panel: e.target.value })}
													>
														{Object.entries(PANELS).map(([id, p]) => (
															<option key={id} value={id}>
																{p.title}
															</option>
														))}
													</select>
												}
												controls={
													ci === 0 && ri === 0 ? (
														<Button variant="ghost" size="sm" className="text-muted-foreground text-xs" onClick={reset}>
															Reset layout
														</Button>
													) : null
												}
											>
												<def.Component />
											</PanelShell>
										</ResizablePanel>
									</Fragment>
								);
							})}
						</ResizablePanelGroup>
					</ResizablePanel>
				</Fragment>
			))}
		</ResizablePanelGroup>
	);
}
