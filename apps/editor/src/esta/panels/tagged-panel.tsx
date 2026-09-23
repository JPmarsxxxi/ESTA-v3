"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/ui";
import { api, post } from "../api";
import { ConflictBanner, useSessionDoc } from "../doc";
import { useWorkspace } from "../store";
import { LineEditor } from "./line-editor";

// The expressive-clone checkpoint (audio skill steps 3-6): review and edit the
// delivery markup in script.tagged.md, re-run tag-check, approve, and redo
// single lines with `expressive --only`.

type VoiceLine = { id: string; section: string; text: string; emotion: string | null; pace_label: string | null; pause_after_ms: number; voice: string | null; guide: string | null };
type VoiceScript = { voice_sample?: string; line_count?: number; lines: VoiceLine[] };

const isHeader = (line: string) => /^\[(HOOK|BODY|CTA)\]\s*$/.test(line.trim());

// "{disgusted, weary | pace: slow | pause: 600} text with *stress*"
function TaggedLine({ line }: { line: string }) {
	const m = /^\s*\{([^}]*)\}\s*(.*)$/.exec(line);
	const tags = m ? m[1].split("|").map((t) => t.trim()).filter(Boolean) : [];
	const text = m ? m[2] : line;
	return (
		<span className="space-x-1">
			{tags.map((t, i) => (
				<span key={i} className={cn("inline-block rounded px-1 text-[10px]", i === 0 && !t.includes(":") ? "bg-violet-500/15 text-violet-600 dark:text-violet-300" : "bg-accent text-muted-foreground")}>
					{t}
				</span>
			))}
			<span>
				{text.split(/(\*[^*]+\*|\[[^\]]+\])/).map((part, i) =>
					part.startsWith("*") ? (
						<strong key={i}>{part.slice(1, -1)}</strong>
					) : part.startsWith("[") ? (
						<span key={i} className="text-muted-foreground italic">
							{part}
						</span>
					) : (
						part
					),
				)}
			</span>
		</span>
	);
}

export function TaggedPanel() {
	const { session, pipeline, lastFile } = useWorkspace();
	const doc = useSessionDoc<string[]>({ path: "script.tagged.md", parse: (t) => t.split("\n"), serialize: (l) => l.join("\n") });
	const [voice, setVoice] = useState<VoiceScript | null>(null);
	const [redo, setRedo] = useState<Set<string>>(new Set());
	const [msg, setMsg] = useState<string | null>(null);
	const approved = Boolean(pipeline?.taggedScript.approved);
	const base = `/_pipeline/${encodeURIComponent(session)}`;
	const voiceVersion = lastFile?.path === "voice_script.json" ? lastFile.mtimeMs : 0;

	useEffect(() => {
		api<VoiceScript>(`/api/sessions/${encodeURIComponent(session)}/voice_script.json`).then(setVoice, () => setVoice(null));
	}, [session, voiceVersion]);

	const run = async ({ action, params }: { action: string; params?: Record<string, string> }) => {
		setMsg(null);
		try {
			await post({ path: `${base}/run`, body: { action, params } });
			setMsg(`Started ${action}; follow it in Jobs.`);
		} catch (e) {
			setMsg(e instanceof Error ? e.message : String(e));
		}
	};
	const sample = voice?.voice_sample?.split(/[\\/]/).pop();

	if (doc.missing) return <p className="text-muted-foreground p-3 text-sm">No script.tagged.md yet. Run &quot;Tag script for delivery&quot; in the Voice stage.</p>;
	if (doc.value === null) return <p className="text-muted-foreground p-3 text-sm">Loading…</p>;

	return (
		<div className="space-y-3 p-3 text-sm">
			<div className="flex flex-wrap items-center gap-2">
				<span className={cn("rounded px-1.5 py-0.5 text-xs", approved ? "bg-constructive/15 text-constructive" : "bg-violet-500/15 text-violet-600 dark:text-violet-300")}>
					{approved ? "Delivery plan approved" : "Needs approval before generation"}
				</span>
				<Button size="sm" variant="outline" disabled={!sample} title={sample ? `tag-check with ${sample}` : "voice_script.json names no sample yet"} onClick={() => sample && run({ action: "tag-check", params: { sample } })}>
					Re-run tag-check
				</Button>
				<Button
					size="sm"
					variant={approved ? "ghost" : "default"}
					onClick={() => post({ path: `${base}/approve`, body: { checkpoint: "tagged_script", revoke: approved } }).catch((e) => setMsg(String(e.message || e)))}
				>
					{approved ? "Revoke approval" : "Approve delivery plan"}
				</Button>
			</div>
			{msg && <p className="text-muted-foreground text-xs">{msg}</p>}
			{doc.conflict && <ConflictBanner what="script.tagged.md" onResolve={doc.resolve} />}
			<p className="text-muted-foreground text-xs">Edit a line&apos;s emotion, *stress*, pauses or pace, then re-run tag-check so voice_script.json matches.</p>
			<LineEditor lines={doc.value} onChange={doc.change} isHeader={isHeader} renderLine={(l) => <TaggedLine line={l} />} saving={doc.saving} />
			{voice && (
				<section className="space-y-1.5">
					<div className="flex items-center justify-between">
						<h3 className="text-muted-foreground text-[11px] uppercase">
							Parsed lines ({voice.lines.length}){sample ? ` · sample ${sample}` : ""}
						</h3>
						<Button size="sm" variant="outline" disabled={!redo.size || !approved} title={approved ? "" : "approve the delivery plan first"} onClick={() => run({ action: "expressive", params: { only: [...redo].join(",") } })}>
							Redo {redo.size || ""} line{redo.size === 1 ? "" : "s"}
						</Button>
					</div>
					<div className="max-h-72 overflow-auto rounded-md border">
						{voice.lines.map((l) => (
							<label key={l.id} className="hover:bg-accent/50 flex cursor-pointer items-start gap-2 border-b px-2 py-1 text-xs">
								<input
									type="checkbox"
									className="mt-0.5"
									checked={redo.has(l.id)}
									onChange={(e) => {
										const next = new Set(redo);
										if (e.target.checked) next.add(l.id);
										else next.delete(l.id);
										setRedo(next);
									}}
								/>
								<span className="text-muted-foreground w-9 shrink-0 font-mono">{l.id}</span>
								<span className="text-muted-foreground w-24 shrink-0 truncate">{[l.emotion, l.pace_label, l.pause_after_ms ? `${l.pause_after_ms}ms` : ""].filter(Boolean).join(" · ")}</span>
								<span className="min-w-0 flex-1">{l.text}</span>
								{(l.voice || l.guide) && <span className="text-muted-foreground shrink-0">{l.voice ?? `guide: ${l.guide}`}</span>}
							</label>
						))}
					</div>
				</section>
			)}
		</div>
	);
}
