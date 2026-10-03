"use client";

import { useCallback, useEffect, useState, type DragEvent } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/ui";
import { BACKEND, CLIENT_ID, api, post, sessionFileUrl } from "../api";
import { useWorkspace } from "../store";
import { inputClass } from "../ui";

type Ref = { file: string; source: string; role: "world" | "character"; role_source: string; note: string };
type Index = { images: Ref[]; look_style_auto?: string; look_style: string };

// SPEC.md Part 5 (M8.3): the session's look refs. tools/look/refs.py owns the index; this card drops files,
// flips roles and runs Describe, which tags roles and writes look_style when it is empty.
export function LookPanel() {
	const { session, lastFile, jobs } = useWorkspace();
	const [data, setData] = useState<Index | null>(null);
	const [style, setStyle] = useState("");
	const [status, setStatus] = useState("");
	const [over, setOver] = useState(false);
	const base = `/_look/${encodeURIComponent(session)}`;

	const load = useCallback(() => {
		api<Index>(base)
			.then((d) => {
				setData(d);
				setStyle(d.look_style);
			})
			.catch((e) => setStatus(e instanceof Error ? e.message : "failed to load"));
	}, [base]);
	useEffect(load, [load]);
	useEffect(() => {
		if (lastFile?.session === session && /^(look_refs|requirements)\.json$/.test(lastFile.path)) load();
	}, [lastFile, session, load]);

	const act = async (fn: () => Promise<unknown>) => {
		try {
			await fn();
			setStatus("");
			load();
		} catch (e) {
			setStatus(e instanceof Error ? e.message : "failed");
		}
	};

	const drop = async (e: DragEvent) => {
		e.preventDefault();
		setOver(false);
		const files = [...e.dataTransfer.files].filter((f) => f.type.startsWith("image/"));
		const notes: string[] = [];
		for (const f of files) {
			const res = await fetch(`${BACKEND}${base}/add`, {
				method: "POST",
				headers: { "Content-Type": f.type || "application/octet-stream", "X-Filename": f.name, "X-Esta-Client": CLIENT_ID },
				body: f,
			});
			const out = await res.json().catch(() => ({ error: "bad response" }));
			if (out.rejected?.length) notes.push(...out.rejected.map((r: { file: string; why: string }) => `${r.file}: ${r.why}`));
			if (out.duplicates?.length) notes.push(...out.duplicates.map((d: string) => `${d}: already added`));
			if (out.error) notes.push(`${f.name}: ${out.error}`);
		}
		setStatus(notes.join(" · "));
		load();
	};

	const describing = jobs.some((j) => j.action === "look-describe" && j.status === "running");
	const images = data?.images ?? [];

	return (
		<div className="flex size-full min-h-0 flex-col gap-2 overflow-auto p-2 text-sm">
			<div
				className={cn("text-muted-foreground rounded border border-dashed p-3 text-center text-xs", over && "border-primary text-foreground")}
				onDragOver={(e) => {
					e.preventDefault();
					setOver(true);
				}}
				onDragLeave={() => setOver(false)}
				onDrop={drop}
			>
				Drop reference images here (png, jpg, webp): the world, the characters, faces, proportions.
			</div>
			{status && <p className="text-caution text-xs">{status}</p>}
			{images.length > 0 && (
				<div className="grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-2">
					{images.map((im) => (
						<figure key={im.file} className="m-0 min-w-0 text-xs">
							{/* eslint-disable-next-line @next/next/no-img-element */}
							<img src={sessionFileUrl({ session, path: `look_refs/${im.file}` })} alt={im.note || im.source} className="aspect-square w-full rounded object-cover" />
							<div className="mt-1 flex gap-1">
								{(["world", "character"] as const).map((role) => (
									<Button
										key={role}
										size="sm"
										variant={im.role === role ? "default" : "outline"}
										className="h-6 flex-1 px-1 text-xs"
										onClick={() => act(() => post({ path: `${base}/role`, body: { file: im.file, role } }))}
									>
										{role}
									</Button>
								))}
								<Button size="sm" variant="ghost" className="h-6 px-1 text-xs" aria-label={`Remove ${im.source}`} onClick={() => act(() => post({ path: `${base}/remove`, body: { file: im.file } }))}>
									x
								</Button>
							</div>
							{im.note && <figcaption className="text-muted-foreground mt-1">{im.note}</figcaption>}
						</figure>
					))}
				</div>
			)}
			<div className="flex items-center gap-2">
				<Button
					size="sm"
					variant="outline"
					disabled={!images.length || describing}
					onClick={() => act(() => post({ path: `/_pipeline/${encodeURIComponent(session)}/run`, body: { action: "look-describe", params: {} } }))}
				>
					{describing ? "Describing…" : "Describe"}
				</Button>
				<span className="text-muted-foreground text-xs">Haiku tags each image and writes the look line when it is empty.</span>
			</div>
			<label className="text-xs">
				<span className="text-muted-foreground">look_style (appended to every generated prompt; keep it under ~30 words)</span>
				<textarea className={`${inputClass} mt-1 min-h-16`} value={style} onChange={(e) => setStyle(e.target.value)} />
			</label>
			<div className="flex items-center gap-2">
				<Button size="sm" disabled={style === (data?.look_style ?? "")} onClick={() => act(() => post({ path: `${base}/style`, body: { look_style: style } }))}>
					Save look
				</Button>
				{data?.look_style_auto && data.look_style_auto !== style && (
					<Button size="sm" variant="ghost" onClick={() => setStyle(data.look_style_auto ?? "")}>
						Use the Haiku line
					</Button>
				)}
			</div>
		</div>
	);
}
