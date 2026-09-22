"use client";

import { useEffect, useState } from "react";
import { api, apiText, sessionFileUrl } from "../api";
import { useWorkspace } from "../store";
import { inputClass } from "../ui";

type FileRow = { path: string; size: number; mtimeMs: number };

// The artifact each stage produces or reviews, shown first.
const STAGE_FILE: Record<string, string> = {
	requirements: "requirements.json",
	"voice-profile": "voice_profile.md",
	research: "research.json",
	script: "script.md",
	voice: "script.tagged.md",
	timestamps: "timestamps.json",
	style: "style_analysis.json",
	plan: "plan.json",
	assets: "assets.json",
	edit: "pipeline.json",
};

const TEXT = /\.(json|jsonl|md|txt|log|py|yaml|yml)$/i;
const MEDIA = /\.(mp4|webm|mov|wav|mp3|m4a|jpg|jpeg|png|gif|webp)$/i;
const MAX_PREVIEW = 400_000;

export function FilesPanel() {
	const { session, stage, lastFile } = useWorkspace();
	const [files, setFiles] = useState<FileRow[]>([]);
	const [path, setPath] = useState(STAGE_FILE[stage] ?? "requirements.json");
	const [loaded, setLoaded] = useState<{ key: string; content: string | null; error: string | null } | null>(null);

	useEffect(() => {
		api<{ files: FileRow[] }>(`/_files/${encodeURIComponent(session)}/list`)
			.then((d) => setFiles(d.files))
			.catch(() => {});
	}, [session, lastFile?.path, lastFile?.exists]);

	const row = files.find((f) => f.path === path);
	const version = lastFile?.path === path ? lastFile.mtimeMs : 0;
	const tooLarge = Boolean(row && row.size > MAX_PREVIEW);
	const key = `${path}@${version}@${row?.mtimeMs ?? 0}`;

	// Read-only view: an external change to the shown file just reloads it.
	useEffect(() => {
		if (!TEXT.test(path) || tooLarge) return;
		apiText(`/api/sessions/${encodeURIComponent(session)}/${path.split("/").map(encodeURIComponent).join("/")}`)
			.then((t) => {
				let content = t;
				if (path.endsWith(".json")) {
					try {
						content = JSON.stringify(JSON.parse(t), null, 2);
					} catch {
						/* show raw */
					}
				}
				setLoaded({ key, content, error: null });
			})
			.catch(() => setLoaded({ key, content: null, error: `${path} doesn't exist yet.` }));
	}, [session, path, tooLarge, key]);

	const current = loaded && loaded.key.startsWith(`${path}@`) ? loaded : null;
	const content = !TEXT.test(path) ? null : tooLarge ? `(${Math.round((row?.size ?? 0) / 1024)} KB, too large to preview; open it from disk)` : (current?.content ?? null);
	const error = TEXT.test(path) && !tooLarge ? (current?.error ?? null) : null;
	const options = [...new Set([path, ...files.map((f) => f.path)])];
	const url = sessionFileUrl({ session, path });

	return (
		<div className="flex size-full min-h-0 flex-col text-sm">
			<div className="shrink-0 border-b p-1.5">
				<select className={`${inputClass} h-7 py-0 text-xs`} value={path} onChange={(e) => setPath(e.target.value)}>
					{options.map((p) => (
						<option key={p} value={p}>
							{p}
							{files.some((f) => f.path === p) ? "" : " (missing)"}
						</option>
					))}
				</select>
			</div>
			<div className="min-h-0 flex-1 overflow-auto">
				{error && <p className="text-muted-foreground p-3 text-xs">{error}</p>}
				{content !== null && <pre className="p-2 font-mono text-[11px] leading-snug whitespace-pre-wrap">{content}</pre>}
				{MEDIA.test(path) && row && (
					<div className="p-2">
						{/\.(wav|mp3|m4a)$/i.test(path) && (
							<audio controls src={url} className="w-full">
								<track kind="captions" />
							</audio>
						)}
						{/\.(mp4|webm|mov)$/i.test(path) && (
							<video controls src={url} className="max-h-[60vh] w-full">
								<track kind="captions" />
							</video>
						)}
						{/\.(jpg|jpeg|png|gif|webp)$/i.test(path) && (
							// eslint-disable-next-line @next/next/no-img-element
							<img src={url} alt={path} className="max-w-full" />
						)}
					</div>
				)}
			</div>
		</div>
	);
}
