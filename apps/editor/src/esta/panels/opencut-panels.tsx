"use client";

import { useEffect, useMemo, type ReactNode } from "react";
import { AssetsPanel } from "@/components/editor/panels/assets";
import { PropertiesPanel } from "@/components/editor/panels/properties";
import { useEditor } from "@/editor/use-editor";
import { getGuidePreviewOverlaySource } from "@/guides";
import { PreviewPanel } from "@/preview/components";
import { createPreviewOverlayControl, isPreviewOverlayVisible, mergePreviewOverlaySources } from "@/preview/overlays";
import { usePreviewStore } from "@/preview/preview-store";
import { bookmarkNotesPreviewOverlay, getBookmarkPreviewOverlaySource } from "@/timeline/bookmarks/index";
import { Timeline } from "@/timeline/components";
import { useOpenCut } from "../opencut/host";
import { ConflictBanner } from "./editor-panel";

function Gate({ children }: { children: ReactNode }) {
	const { status, error, open } = useOpenCut();
	useEffect(open, [open]);
	if (status === "ready") return <div className="size-full min-h-0">{children}</div>;
	return (
		<div className="text-muted-foreground p-4 text-sm">
			{status === "missing" && "No editor project yet. Build it from the Editor project panel once render has run."}
			{(status === "idle" || status === "loading") && "Loading the editor project..."}
			{status === "error" && <span className="text-destructive">Could not load the editor project: {error}</span>}
		</div>
	);
}

// The same preview overlays (guides, bookmark notes) as OpenCut's editor page.
function Preview() {
	const activeScene = useEditor((e) => e.scenes.getActiveSceneOrNull());
	const currentTime = useEditor((e) => e.playback.getCurrentTime());
	const activeGuide = usePreviewStore((s) => s.activeGuide);
	const overlays = usePreviewStore((s) => s.overlays);
	const setOverlayVisibility = usePreviewStore((s) => s.setOverlayVisibility);
	const showNotes = isPreviewOverlayVisible({ overlay: bookmarkNotesPreviewOverlay, overlays });
	const source = useMemo(
		() =>
			mergePreviewOverlaySources({
				sources: [
					getGuidePreviewOverlaySource({ guideId: activeGuide }),
					activeScene
						? getBookmarkPreviewOverlaySource({ bookmarks: activeScene.bookmarks, time: currentTime, isVisible: showNotes })
						: { definitions: [bookmarkNotesPreviewOverlay], instances: [] },
				],
			}),
		[activeGuide, activeScene, currentTime, showNotes],
	);
	const controls = useMemo(() => source.definitions.map((overlay) => createPreviewOverlayControl({ overlay, overlays })), [source.definitions, overlays]);
	return <PreviewPanel overlayControls={controls} overlayInstances={source.instances} onOverlayVisibilityChange={setOverlayVisibility} />;
}

export const OcPreviewPanel = () => (
	<Gate>
		<Preview />
	</Gate>
);

export const OcTimelinePanel = () => (
	<Gate>
		<div className="flex size-full min-h-0 flex-col">
			<ConflictBanner />
			<div className="min-h-0 flex-1">
				<Timeline />
			</div>
		</div>
	</Gate>
);

export const OcAssetsPanel = () => (
	<Gate>
		<AssetsPanel />
	</Gate>
);

export const OcPropertiesPanel = () => (
	<Gate>
		<PropertiesPanel />
	</Gate>
);
