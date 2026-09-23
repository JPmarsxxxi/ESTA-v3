"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiError, post } from "../api";
import { useSessionDoc } from "../doc";
import { useWorkspace } from "../store";
import { Field, inputClass } from "../ui";

// Edit requirements.json in place (v2's "tweak" path), through the same
// validators the requirements skill and the create form use.

type Reqs = Record<string, unknown> & {
	topic?: string;
	style?: string;
	duration_range?: string;
	orientation?: string;
	licensing?: string;
	comments?: string;
	example_scripts?: Array<{ text: string }> | string;
	script_text?: string | null;
};

type Form = { topic: string; style: string; duration_range: string; orientation: string; licensing: string; comments: string; examples: string; script_text: string };

function formOf(r: Reqs): Form {
	return {
		topic: r.topic ?? "",
		style: r.style ?? "",
		duration_range: r.duration_range ?? "",
		orientation: r.orientation ?? "vertical",
		licensing: r.licensing ?? "free_only",
		comments: r.comments ?? "",
		examples: Array.isArray(r.example_scripts) ? r.example_scripts.map((e) => e.text).join("\n---\n") : "",
		script_text: r.script_text ?? "",
	};
}

export function RequirementsPanel() {
	const { session, pipeline } = useWorkspace();
	const doc = useSessionDoc<Reqs>({ path: "requirements.json", parse: (t) => JSON.parse(t), serialize: (v) => JSON.stringify(v, null, 2) });
	const [draft, setDraft] = useState<Form | null>(null);
	const [errors, setErrors] = useState<Record<string, string>>({});
	const [saved, setSaved] = useState<string | null>(null);

	if (doc.missing) return <p className="text-muted-foreground p-3 text-sm">No requirements.json yet. Fill them in when creating the session, or run the requirements skill in chat.</p>;
	if (!doc.value) return <p className="text-muted-foreground p-3 text-sm">Loading…</p>;

	// Untouched form follows disk (external edits show up live); a draft holds until saved.
	const form = draft ?? formOf(doc.value);
	const set = (k: keyof Form) => (e: { target: { value: string } }) => setDraft({ ...form, [k]: e.target.value });
	const approved = Boolean(pipeline?.approvals.requirements);

	const save = async () => {
		setErrors({});
		try {
			await post({
				path: `/_sessions/${encodeURIComponent(session)}/requirements`,
				body: {
					...form,
					example_scripts: form.examples
						.split(/\n-{3,}\n/)
						.map((t) => t.trim())
						.filter(Boolean),
				},
			});
			setDraft(null);
			setSaved(`Saved ${new Date().toLocaleTimeString()}`);
		} catch (e) {
			if (e instanceof ApiError && e.body.fields && typeof e.body.fields === "object") {
				setErrors(Object.fromEntries(Object.entries(e.body.fields).map(([k, v]) => [k, String(v)])));
			} else setErrors({ _: e instanceof Error ? e.message : String(e) });
		}
	};

	return (
		<div className="space-y-3 p-3 text-sm">
			{approved && draft && <div className="bg-caution/15 rounded-md px-2.5 py-1.5 text-xs">Requirements are already approved. Stages downstream won&apos;t re-run on their own after you change them.</div>}
			<Field label="Topic" error={errors.topic}>
				<input className={inputClass} value={form.topic} onChange={set("topic")} />
			</Field>
			<div className="grid grid-cols-2 gap-3">
				<Field label="Style" error={errors.style}>
					<input className={inputClass} value={form.style} onChange={set("style")} />
				</Field>
				<Field label="Duration" error={errors.duration_range}>
					<input className={inputClass} value={form.duration_range} onChange={set("duration_range")} />
				</Field>
				<Field label="Orientation">
					<select className={inputClass} value={form.orientation} onChange={set("orientation")}>
						<option value="vertical">Vertical 9:16</option>
						<option value="horizontal">Horizontal 16:9</option>
						<option value="square">Square 1:1</option>
					</select>
				</Field>
				<Field label="Licensing">
					<select className={inputClass} value={form.licensing} onChange={set("licensing")}>
						<option value="free_only">Free only</option>
						<option value="fair_use_ok">Fair use OK</option>
					</select>
				</Field>
			</div>
			<Field label="Comments">
				<textarea className={`${inputClass} min-h-16`} value={form.comments} onChange={set("comments")} />
			</Field>
			<Field label="Example scripts" hint="Separate scripts with a line of ---. Adding samples brings the voice profiler back into the flow.">
				<textarea className={`${inputClass} min-h-20 font-mono text-xs`} value={form.examples} onChange={set("examples")} />
			</Field>
			<Field label="Uploaded script" hint="A pasted script skips the scriptwriter">
				<textarea className={`${inputClass} min-h-20 font-mono text-xs`} value={form.script_text} onChange={set("script_text")} />
			</Field>
			{errors._ && <p className="text-destructive text-xs">{errors._}</p>}
			<div className="flex items-center gap-2">
				<Button size="sm" disabled={!draft} onClick={save}>
					Save requirements
				</Button>
				{draft && (
					<Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
						Discard changes
					</Button>
				)}
				<span className="text-muted-foreground text-xs">{saved}</span>
			</div>
		</div>
	);
}
