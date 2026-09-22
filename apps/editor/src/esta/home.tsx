"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ApiError, api, post, type SessionSummary } from "./api";
import { Field, inputClass } from "./ui";

const STYLE_PRESETS = ["funny", "documentary", "serious", "graphic-heavy", "tutorial"];

function when(ms: number) {
	return ms ? new Date(ms).toLocaleString() : "";
}

export function EstaHome() {
	const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [mode, setMode] = useState<"list" | "create" | "import">("list");

	const load = useCallback(() => {
		api<{ sessions: SessionSummary[] }>("/_sessions/list?all=1")
			.then((d) => {
				setSessions(d.sessions);
				setError(null);
			})
			.catch(() => setError("The ESTA backend isn't reachable on :8787. Start everything with `bun run dev` from the repo root."));
	}, []);
	useEffect(load, [load]);

	return (
		<div className="bg-background text-foreground min-h-screen">
			<header className="flex h-14 items-center justify-between border-b px-6">
				<div className="flex items-baseline gap-3">
					<span className="text-lg font-semibold">ESTA</span>
					<span className="text-muted-foreground text-sm">video factory</span>
				</div>
				<div className="flex gap-2">
					<Button variant="outline" size="sm" onClick={() => setMode("import")}>
						Import from v2
					</Button>
					<Button size="sm" onClick={() => setMode("create")}>
						New video
					</Button>
				</div>
			</header>
			<main className="mx-auto max-w-4xl px-6 py-8">
				{error && <div className="border-destructive/40 bg-destructive/10 mb-6 rounded-md border p-3 text-sm">{error}</div>}
				{mode === "create" && <CreateForm onCancel={() => setMode("list")} />}
				{mode === "import" && (
					<ImportPanel
						onDone={() => {
							setMode("list");
							load();
						}}
					/>
				)}
				{mode === "list" && (
					<section>
						<h1 className="mb-4 text-xl font-semibold">Sessions</h1>
						{sessions === null && !error && <p className="text-muted-foreground text-sm">Loading…</p>}
						{sessions?.length === 0 && (
							<p className="text-muted-foreground text-sm">No sessions yet. Start a new video or import one from v2.</p>
						)}
						<ul className="divide-y rounded-md border">
							{sessions?.map((s) => (
								<li key={s.id}>
									<Link href={`/esta/${encodeURIComponent(s.id)}`} className="hover:bg-accent flex items-center justify-between gap-4 px-4 py-3">
										<div className="min-w-0">
											<div className="truncate font-medium">{s.topic || s.id}</div>
											<div className="text-muted-foreground truncate text-xs">
												{s.id}
												{s.template ? ` · ${s.template}` : " · no pipeline yet"}
											</div>
										</div>
										<div className="text-muted-foreground shrink-0 text-right text-xs">
											{s.hasProject && <div className="text-foreground">rendered</div>}
											<div>{when(s.modifiedAt)}</div>
										</div>
									</Link>
								</li>
							))}
						</ul>
					</section>
				)}
			</main>
		</div>
	);
}

// The fields the v2 requirements skill collects conversationally
// (tools/requirements/schema.py); the backend runs the same validators.
function CreateForm({ onCancel }: { onCancel: () => void }) {
	const router = useRouter();
	const [form, setForm] = useState({
		topic: "",
		style: "documentary",
		duration_range: "2-3 minutes",
		orientation: "vertical",
		licensing: "free_only",
		comments: "",
		examples: "",
		script_text: "",
	});
	const [errors, setErrors] = useState<Record<string, string>>({});
	const [busy, setBusy] = useState(false);
	const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

	const submit = async () => {
		setBusy(true);
		setErrors({});
		try {
			const examples = form.examples
				.split(/\n-{3,}\n/)
				.map((t) => t.trim())
				.filter(Boolean);
			const { id } = await post<{ id: string }>({
				path: "/_sessions/create",
				body: { ...form, example_scripts: examples },
			});
			router.push(`/esta/${encodeURIComponent(id)}`);
		} catch (e) {
			if (e instanceof ApiError && e.body.fields && typeof e.body.fields === "object") {
				setErrors(Object.fromEntries(Object.entries(e.body.fields).map(([k, v]) => [k, String(v)])));
			} else setErrors({ _: e instanceof Error ? e.message : String(e) });
			setBusy(false);
		}
	};

	return (
		<section className="space-y-4">
			<h1 className="text-xl font-semibold">New video</h1>
			<Field label="Topic" error={errors.topic}>
				<input className={inputClass} value={form.topic} onChange={set("topic")} placeholder="What's the video about, and what's the angle?" />
			</Field>
			<div className="grid grid-cols-2 gap-4">
				<Field label="Style" error={errors.style} hint="A preset or your own words">
					<input className={inputClass} list="esta-styles" value={form.style} onChange={set("style")} />
					<datalist id="esta-styles">
						{STYLE_PRESETS.map((s) => (
							<option key={s} value={s} />
						))}
					</datalist>
				</Field>
				<Field label="Duration" error={errors.duration_range} hint="e.g. 30 seconds, 2-3 minutes">
					<input className={inputClass} value={form.duration_range} onChange={set("duration_range")} />
				</Field>
				<Field label="Orientation">
					<select className={inputClass} value={form.orientation} onChange={set("orientation")}>
						<option value="vertical">Vertical 9:16</option>
						<option value="horizontal">Horizontal 16:9</option>
						<option value="square">Square 1:1</option>
					</select>
				</Field>
				<Field label="Licensing" hint="Which sources assets and found-audio may use">
					<select className={inputClass} value={form.licensing} onChange={set("licensing")}>
						<option value="free_only">Free only (CC / PD / royalty-free)</option>
						<option value="fair_use_ok">Fair use OK (also copyrighted clips)</option>
					</select>
				</Field>
			</div>
			<Field label="Comments" hint="Tone, audience, anything the script should hit">
				<textarea className={`${inputClass} min-h-20`} value={form.comments} onChange={set("comments")} />
			</Field>
			<Field label="Example scripts (optional)" hint="Paste your own writing so the voice profiler can learn it. Separate scripts with a line of ---">
				<textarea className={`${inputClass} min-h-24 font-mono text-xs`} value={form.examples} onChange={set("examples")} />
			</Field>
			<Field label="Your own script (optional)" hint="Paste a finished script to skip the scriptwriter">
				<textarea className={`${inputClass} min-h-24 font-mono text-xs`} value={form.script_text} onChange={set("script_text")} />
			</Field>
			{errors._ && <p className="text-destructive text-sm">{errors._}</p>}
			<div className="flex gap-2">
				<Button onClick={submit} disabled={busy || !form.topic.trim()}>
					{busy ? "Creating…" : "Create session"}
				</Button>
				<Button variant="ghost" onClick={onCancel}>
					Cancel
				</Button>
			</div>
		</section>
	);
}

function ImportPanel({ onDone }: { onDone: () => void }) {
	const [list, setList] = useState<{ root: string; sessions: SessionSummary[] } | null>(null);
	const [conflict, setConflict] = useState<string | null>(null);
	const [renameTo, setRenameTo] = useState("");
	const [busy, setBusy] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		api<{ root: string; sessions: SessionSummary[] }>("/_sessions/import").then(setList).catch((e) => setError(String(e.message || e)));
	}, []);

	const run = async ({ id, mode, newId }: { id: string; mode?: "overwrite" | "rename"; newId?: string }) => {
		setBusy(id);
		setError(null);
		try {
			await post({ path: "/_sessions/import", body: { id, mode, newId } });
			setConflict(null);
			onDone();
		} catch (e) {
			if (e instanceof ApiError && e.status === 409) {
				setConflict(id);
				setRenameTo(`${id}-v2`);
			} else setError(e instanceof Error ? e.message : String(e));
		}
		setBusy(null);
	};

	return (
		<section className="space-y-4">
			<div className="flex items-center justify-between">
				<h1 className="text-xl font-semibold">Import from v2</h1>
				<Button variant="ghost" size="sm" onClick={onDone}>
					Back
				</Button>
			</div>
			{list && <p className="text-muted-foreground text-sm">Copies a session folder from {list.root}. The v2 folder is left untouched.</p>}
			{error && <p className="text-destructive text-sm">{error}</p>}
			<ul className="divide-y rounded-md border">
				{list?.sessions.map((s) => (
					<li key={s.id} className="px-4 py-3">
						<div className="flex items-center justify-between gap-4">
							<div className="min-w-0">
								<div className="truncate font-medium">{s.topic || s.id}</div>
								<div className="text-muted-foreground truncate text-xs">
									{s.id}
									{s.existsInV3 ? " · already in v3" : ""}
								</div>
							</div>
							<Button size="sm" variant="outline" disabled={busy !== null} onClick={() => run({ id: s.id })}>
								{busy === s.id ? "Copying…" : "Import"}
							</Button>
						</div>
						{conflict === s.id && (
							<div className="bg-accent mt-3 space-y-2 rounded-md p-3 text-sm">
								<p>
									<strong>{s.id}</strong> already exists in v3. Sessions are never merged: overwrite the v3 copy, or import under a new name.
								</p>
								<div className="flex flex-wrap items-center gap-2">
									<Button size="sm" variant="destructive" onClick={() => run({ id: s.id, mode: "overwrite" })}>
										Overwrite v3 copy
									</Button>
									<input className={`${inputClass} h-7 w-72`} value={renameTo} onChange={(e) => setRenameTo(e.target.value)} />
									<Button size="sm" variant="outline" onClick={() => run({ id: s.id, mode: "rename", newId: renameTo })}>
										Import as new name
									</Button>
									<Button size="sm" variant="ghost" onClick={() => setConflict(null)}>
										Cancel
									</Button>
								</div>
							</div>
						)}
					</li>
				))}
			</ul>
		</section>
	);
}
