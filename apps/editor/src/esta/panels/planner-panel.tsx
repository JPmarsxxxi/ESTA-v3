"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/ui";
import { BACKEND, CLIENT_ID, api, post } from "../api";
import { ConflictBanner } from "../doc";
import { useWorkspace } from "../store";
import { inputClass } from "../ui";

// Port of v2 tools/planner/index.html: same fields, same endpoints, same
// autosave-on-leave, Rewrite and structural commands.

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Shot = Record<string, any>;
type Fields = { desc: string; type: string; spec: string; fx: string; queries: string; music: string; sfx: string; caption: string; ocaption: string; odesc: string };
type Rewrite = { status: string; proposal?: Record<string, unknown>; cost?: number; error?: string };

// SFX entries are bare strings or {sound,on}; edited one per line as "sound | word".
const sfxToText = (arr: unknown[] | undefined) =>
	(arr || []).map((e) => (e && typeof e === "object" ? `${(e as Shot).sound}${(e as Shot).on ? " | " + (e as Shot).on : ""}` : String(e))).join("\n");
const textToSfx = (t: string) =>
	t
		.split("\n")
		.map((l) => l.trim())
		.filter(Boolean)
		.map((l) => {
			const [sound, on] = l.split("|").map((x) => x.trim());
			return on ? { sound, on } : sound;
		});
const queriesText = (v: Shot) => (v.search_sources || []).map((e: Shot) => `${e.source}: ${(e.queries || []).join(", ")}`).join("\n");

function fieldsOf(s: Shot): Fields {
	const v = s.visual || {};
	return {
		desc: v.desc || "",
		type: v.type || "REAL_FOOTAGE",
		spec: v.specificity || "low",
		fx: (v.fx || []).join(", "),
		queries: queriesText(v),
		music: s.audio_layer?.music || "",
		sfx: sfxToText(s.audio_layer?.sfx),
		caption: s.text?.caption || "",
		ocaption: s.overlay?.caption || "",
		odesc: s.overlay?.desc || "",
	};
}

// Pull the form back into the shot, preserving every field the form doesn't surface.
function collect({ shot, f }: { shot: Shot; f: Fields }): Shot {
	const s: Shot = structuredClone(shot);
	const v = (s.visual = s.visual || {});
	v.desc = f.desc.trim();
	v.type = f.type;
	v.specificity = f.spec;
	v.fx = f.fx.split(",").map((x) => x.trim()).filter(Boolean);
	v.search_sources = f.queries
		.split("\n")
		.map((l) => l.trim())
		.filter(Boolean)
		.map((l) => {
			const i = l.indexOf(":");
			const source = (i < 0 ? l : l.slice(0, i)).trim();
			const queries = (i < 0 ? "" : l.slice(i + 1)).split(",").map((q) => q.trim()).filter(Boolean);
			return { source, queries };
		});
	v.search_query = v.search_sources[0]?.queries[0] || v.search_query || "";
	s.audio_layer = s.audio_layer || {};
	s.audio_layer.music = f.music.trim();
	s.audio_layer.sfx = textToSfx(f.sfx);
	s.text = s.text || {};
	s.text.caption = f.caption.trim();
	if (s.overlay) {
		s.overlay.caption = f.ocaption.trim();
		s.overlay.desc = f.odesc.trim();
	}
	return s;
}

// Merge an AI proposal into the form, returning the fields it changed.
function applyProposal({ f, p, shot }: { f: Fields; p: Record<string, unknown>; shot: Shot }): { next: Fields; changed: string[] } {
	const next = { ...f };
	const changed: string[] = [];
	const put = ({ key, value }: { key: keyof Fields; value: string }) => {
		next[key] = value;
		changed.push(key);
	};
	if (p.desc != null) put({ key: "desc", value: String(p.desc) });
	if (p.type != null) put({ key: "type", value: String(p.type) });
	if (p.fx != null) put({ key: "fx", value: (Array.isArray(p.fx) ? p.fx : [p.fx]).join(", ") });
	if (Array.isArray(p.search_queries)) {
		// Spread the new queries over the shot's existing sources.
		const srcs: string[] = (shot.visual?.search_sources || [{ source: "pexels_video" }]).map((e: Shot) => e.source);
		const qs = p.search_queries.map(String);
		const per = Math.ceil(qs.length / srcs.length) || 1;
		put({
			key: "queries",
			value: srcs
				.map((src, i) => `${src}: ${qs.slice(i * per, (i + 1) * per).join(", ")}`)
				.filter((l) => !l.endsWith(": "))
				.join("\n"),
		});
	}
	if (p.music != null) put({ key: "music", value: String(p.music) });
	if (Array.isArray(p.sfx)) put({ key: "sfx", value: sfxToText(p.sfx) });
	if (p.caption != null) put({ key: "caption", value: String(p.caption) });
	return { next, changed };
}

// A shot's identity is its line, not its number: a split renumbers everything below.
const anchorOf = (s: Shot | undefined) => (s ? { line_id: s.line_id, audio: String(s.audio || "").slice(0, 40) } : null);
function resolveAnchor({ shots, a }: { shots: Shot[]; a: ReturnType<typeof anchorOf> }) {
	if (!a) return null;
	const exact = shots.find((s) => s.line_id === a.line_id && String(s.audio || "").slice(0, 40) === a.audio);
	return (exact || shots.find((s) => s.line_id === a.line_id))?.shot_number ?? null;
}

async function saveShot({ session, shot }: { session: string; shot: Shot }) {
	return post<{ ok: boolean }>({ path: "/_plan/api/shot", body: { session, shot } });
}

export function PlannerPanel() {
	const { session, lastFile, selectedShot, selectShot } = useWorkspace();
	const [shots, setShots] = useState<Shot[] | null>(null);
	const [loadError, setLoadError] = useState<string | null>(null);
	const [timingSource, setTimingSource] = useState("");
	const [version, setVersion] = useState(0);
	const [dirty, setDirty] = useState<Set<number>>(new Set());
	const [saved, setSaved] = useState<Set<number>>(new Set());
	const [rewrites, setRewrites] = useState<Record<number, Rewrite>>({});
	const [status, setStatus] = useState("Edits save themselves when you move on. Ctrl+S saves and advances.");
	const [conflict, setConflictState] = useState(false);
	const discarding = useRef(false);
	// While a conflict is open, leaving an edited shot holds its edits here instead
	// of saving them over the disk version; Keep mine writes them, Take theirs drops them.
	const conflictRef = useRef(false);
	const held = useRef(new Map<number, Shot>());
	const disk = useRef<Shot[] | null>(null);
	// Reset only after the re-keyed form has unmounted, or its save-on-leave
	// would write the edits being discarded.
	useEffect(() => {
		discarding.current = false;
	}, [version]);
	const setConflict = useCallback((on: boolean) => {
		conflictRef.current = on;
		setConflictState(on);
	}, []);
	// Which shot is on screen now, readable by a command still running after the
	// form that started it unmounted.
	const viewedAt = useRef(0);
	const dirtyRef = useRef(dirty);
	const shotsRef = useRef(shots);
	const selectedRef = useRef(selectedShot);
	useEffect(() => {
		dirtyRef.current = dirty;
		shotsRef.current = shots;
		selectedRef.current = selectedShot;
	});

	const load = useCallback(
		() =>
			api<{ shots: Shot[]; timing_source: string }>(`/_plan/api/plan?session=${encodeURIComponent(session)}`).then(
				(d) => {
					setShots(d.shots);
					setTimingSource(d.timing_source);
					setLoadError(null);
					return d.shots;
				},
				(e) => {
					setLoadError(e instanceof Error ? e.message : String(e));
					return null;
				},
			),
		[session],
	);
	useEffect(() => void load(), [load]);

	// External write to plan.json (terminal, chat, reconcile): silent reload,
	// unless it changed a shot with unsaved edits, which gets a banner instead.
	// Saves go per shot, so edits to other shots merge without asking.
	useEffect(() => {
		if (lastFile?.path !== "plan.json" || lastFile.by === CLIENT_ID || !lastFile.exists) return;
		const edited = dirtyRef.current;
		if (!edited.size) {
			void load().then(() => setVersion((v) => v + 1));
			return;
		}
		void api<{ shots: Shot[] }>(`/_plan/api/plan?session=${encodeURIComponent(session)}`).then(({ shots: fresh }) => {
			const before = new Map((shotsRef.current ?? []).map((s) => [s.shot_number, JSON.stringify(s)]));
			const clash = fresh.some((s) => edited.has(s.shot_number) && before.get(s.shot_number) !== JSON.stringify(s));
			if (clash) {
				disk.current = fresh;
				return setConflict(true);
			}
			setShots(fresh);
			// The open form keeps its local state only if it has edits of its own.
			if (selectedRef.current == null || !edited.has(selectedRef.current)) setVersion((v) => v + 1);
		});
	}, [lastFile, load, session, setConflict]);

	const current = shots?.find((s) => s.shot_number === selectedShot) ?? null;
	useEffect(() => {
		if (selectedShot != null) viewedAt.current = selectedShot;
	}, [selectedShot]);
	useEffect(() => {
		if (shots?.length && !shots.some((s) => s.shot_number === selectedShot)) selectShot(shots[0].shot_number);
	}, [shots, selectedShot, selectShot]);

	const markDirty = useCallback(({ shot, isDirty }: { shot: number; isDirty: boolean }) => {
		const n = shot;
		setDirty((prev) => {
			if (prev.has(n) === isDirty) return prev;
			const next = new Set(prev);
			if (isDirty) next.add(n);
			else next.delete(n);
			return next;
		});
		if (isDirty) setSaved((prev) => (prev.has(n) ? new Set([...prev].filter((x) => x !== n)) : prev));
	}, []);

	const onSaved = useCallback(
		({ shot, quiet }: { shot: Shot; quiet: boolean }) => {
			markDirty({ shot: shot.shot_number, isDirty: false });
			setSaved((prev) => new Set(prev).add(shot.shot_number));
			setShots((prev) => prev?.map((s) => (s.shot_number === shot.shot_number ? shot : s)) ?? prev);
			setStatus(quiet ? `Auto-saved shot ${shot.shot_number}` : `Saved shot ${shot.shot_number} at ${new Date().toLocaleTimeString()}`);
		},
		[markDirty],
	);

	// Rewrite jobs: one poller for every running proposal.
	useEffect(() => {
		const running = Object.entries(rewrites).filter(([, r]) => r.status === "running");
		if (!running.length) return;
		// An interval, not a one-shot: a still-running job changes no state, so a
		// self-rescheduling poll would stop after its first tick.
		const t = setInterval(async () => {
			for (const [n] of running) {
				const d = await api<Rewrite>(`/_plan/api/rewrite?session=${encodeURIComponent(session)}&shot=${n}`).catch(() => null);
				if (d && d.status !== "running") setRewrites((prev) => ({ ...prev, [Number(n)]: d }));
			}
		}, 1500);
		return () => clearInterval(t);
	}, [rewrites, session]);

	const step = (delta: number) => {
		if (!shots) return;
		const i = shots.findIndex((x) => x.shot_number === selectedShot);
		const j = i + delta;
		if (j >= 0 && j < shots.length) selectShot(shots[j].shot_number);
	};

	const afterCommand = useCallback(
		async ({ landOn, anchor, wasOnTarget, target }: { landOn: number | null; anchor: ReturnType<typeof anchorOf>; wasOnTarget: boolean; target: number }) => {
			const fresh = await load();
			if (!fresh) return;
			setSaved(new Set());
			setDirty((prev) => new Set([...prev].filter((x) => x !== target)));
			setVersion((v) => v + 1);
			// Only jump to the result when the edit targeted the shot being viewed;
			// otherwise re-find where the user already was.
			const landed = wasOnTarget ? (landOn ?? selectedShot) : (resolveAnchor({ shots: fresh, a: anchor }) ?? selectedShot);
			if (landed != null) selectShot(landed);
		},
		[load, selectShot, selectedShot],
	);

	if (loadError) return <p className="text-muted-foreground p-3 text-sm">{loadError.includes("no plan.json") ? "No plan.json yet: run the plan stage first." : loadError}</p>;
	if (!shots) return <p className="text-muted-foreground p-3 text-sm">Loading plan…</p>;

	return (
		<div className="flex size-full min-h-0 text-sm">
			<div className="w-64 shrink-0 overflow-auto border-r">
				<div className="text-muted-foreground sticky top-0 border-b bg-inherit px-2 py-1.5 text-xs uppercase">
					Shots · timing {timingSource}
				</div>
				{shots.map((s) => {
					const v = s.visual || {};
					const tags = [v.type, (v.fx || []).join("+"), s.audio_layer?.sfx?.length ? "sfx" : "", s.overlay ? "overlay" : ""].filter(Boolean).join(" · ");
					const rw = rewrites[s.shot_number]?.status;
					const dot = rw === "running" ? "bg-primary animate-pulse" : rw === "done" ? "bg-violet-500" : dirty.has(s.shot_number) ? "bg-caution animate-pulse" : saved.has(s.shot_number) ? "bg-constructive" : "bg-muted";
					return (
						<button
							key={s.shot_number}
							type="button"
							onClick={() => selectShot(s.shot_number)}
							className={cn("flex w-full gap-2 border-b px-2 py-1.5 text-left", s.shot_number === selectedShot ? "bg-accent" : "hover:bg-accent/50")}
						>
							<span className={cn("mt-1.5 size-2 shrink-0 rounded-full", dot)} />
							<span className="text-muted-foreground w-6 shrink-0 text-right text-xs tabular-nums">{s.shot_number}</span>
							<span className="min-w-0 flex-1">
								<span className="block truncate">{s.audio || "—"}</span>
								<span className="text-muted-foreground block truncate text-[10px]">{tags}</span>
							</span>
						</button>
					);
				})}
			</div>
			<div className="flex min-w-0 flex-1 flex-col">
				{conflict && (
					<div className="p-2 pb-0">
						<ConflictBanner
							what="plan.json"
							onResolve={(keepMine) => {
								setConflict(false);
								const stash = [...held.current.values()];
								held.current.clear();
								if (keepMine) {
									// Disk for everything else; the open form keeps its edits and saves as usual.
									if (disk.current) setShots(disk.current);
									void Promise.all(stash.map((shot) => saveShot({ session, shot }).then(() => onSaved({ shot, quiet: true }))));
									return;
								}
								discarding.current = true;
								setDirty(new Set());
								void load().then(() => setVersion((v) => v + 1));
							}}
						/>
					</div>
				)}
				<div className="min-h-0 flex-1 overflow-auto">
					{current && (
						<ShotForm
							key={`${current.shot_number}:${version}`}
							session={session}
							shot={current}
							rewrite={rewrites[current.shot_number]}
							onRewriteStarted={() => setRewrites((prev) => ({ ...prev, [current.shot_number]: { status: "running" } }))}
							onDirty={(d) => markDirty({ shot: current.shot_number, isDirty: d })}
							shouldDiscard={() => discarding.current}
							hold={(shot) => {
								if (!conflictRef.current) return false;
								held.current.set(shot.shot_number, shot);
								return true;
							}}
							onSaved={onSaved}
							onSaveAndAdvance={() => {
								// Past the last shot, v2 goes back to the first one not saved yet.
								const nx = shots.find((x) => x.shot_number > current.shot_number) ?? shots.find((x) => x.shot_number !== current.shot_number && !saved.has(x.shot_number));
								if (nx) selectShot(nx.shot_number);
							}}
							onStatus={setStatus}
							viewedAt={viewedAt}
							onCommandDone={(r) =>
								afterCommand({
									landOn: r.landOn,
									anchor: anchorOf(shots.find((s) => s.shot_number === r.viewedAt) ?? current),
									wasOnTarget: r.target === r.viewedAt,
									target: r.target,
								})
							}
						/>
					)}
				</div>
				<div className="flex shrink-0 items-center gap-2 border-t px-3 py-1.5">
					<Button size="sm" variant="outline" onClick={() => step(-1)}>
						‹ Prev
					</Button>
					<Button size="sm" variant="outline" onClick={() => step(1)}>
						Next ›
					</Button>
					<span className="text-muted-foreground ml-auto truncate text-xs">{status}</span>
				</div>
			</div>
		</div>
	);
}

function ShotForm({
	session,
	shot,
	rewrite,
	onRewriteStarted,
	onDirty,
	onSaved,
	onSaveAndAdvance,
	onStatus,
	onCommandDone,
	shouldDiscard,
	hold,
	viewedAt,
}: {
	session: string;
	shot: Shot;
	rewrite: Rewrite | undefined;
	onRewriteStarted: () => void;
	onDirty: (dirty: boolean) => void;
	shouldDiscard: () => boolean;
	hold: (shot: Shot) => boolean;
	onSaved: (args: { shot: Shot; quiet: boolean }) => void;
	onSaveAndAdvance: () => void;
	onStatus: (s: string) => void;
	onCommandDone: (r: { landOn: number | null; target: number; viewedAt: number }) => void;
	// The shot on screen when a command finishes: this form unmounts if the user
	// moves on while it runs.
	viewedAt: { current: number };
}) {
	const [f, setF] = useState<Fields>(() => fieldsOf(shot));
	const [isDirty, setIsDirty] = useState(false);
	const [ai, setAi] = useState("");
	const [aiStatus, setAiStatus] = useState(rewrite?.status === "running" ? "rewriting…" : "");
	const [cmd, setCmd] = useState("");
	const [cmdStatus, setCmdStatus] = useState("");
	const [appliedRewrite, setAppliedRewrite] = useState<Rewrite | null>(null);
	const box = useRef<HTMLDivElement>(null);
	const latest = useRef({ f, isDirty, shot, onSaved, shouldDiscard, hold });
	useEffect(() => {
		latest.current = { f, isDirty, shot, onSaved, shouldDiscard, hold };
	});
	const onDirtyRef = useRef(onDirty);
	useEffect(() => {
		onDirtyRef.current = onDirty;
	});
	useEffect(() => onDirtyRef.current(isDirty), [isDirty]);

	const set = (k: keyof Fields) => (e: { target: { value: string } }) => {
		setF((prev) => ({ ...prev, [k]: e.target.value }));
		setIsDirty(true);
	};

	const save = useCallback(
		async ({ quiet }: { quiet: boolean }) => {
			const next = collect({ shot: latest.current.shot, f: latest.current.f });
			try {
				await saveShot({ session, shot: next });
				latest.current.isDirty = false;
				setIsDirty(false);
				latest.current.onSaved({ shot: next, quiet });
				return true;
			} catch (e) {
				onStatus(e instanceof Error ? e.message : "save failed");
				return false;
			}
		},
		[session, onStatus],
	);

	// Ctrl+S saves and advances, as in v2's plan editor.
	useEffect(() => {
		const el = box.current;
		if (!el) return;
		const onKey = async (e: KeyboardEvent) => {
			if (!(e.ctrlKey || e.metaKey) || e.key !== "s") return;
			e.preventDefault();
			if (await save({ quiet: false })) onSaveAndAdvance();
		};
		el.addEventListener("keydown", onKey);
		return () => el.removeEventListener("keydown", onKey);
	}, [save, onSaveAndAdvance]);

	// Leaving a shot commits it; a hard close mid-typing still gets a keepalive send.
	useEffect(() => {
		const onUnload = () => {
			if (!latest.current.isDirty) return;
			void fetch(`${BACKEND}/_plan/api/shot`, {
				method: "POST",
				keepalive: true,
				headers: { "Content-Type": "application/json", "X-Esta-Client": CLIENT_ID },
				body: JSON.stringify({ session, shot: collect({ shot: latest.current.shot, f: latest.current.f }) }),
			});
		};
		window.addEventListener("beforeunload", onUnload);
		return () => {
			window.removeEventListener("beforeunload", onUnload);
			const { isDirty: wasDirty, shot: last, f: fields, onSaved: saved, shouldDiscard: discard, hold: holdBack } = latest.current;
			if (!wasDirty || discard()) return;
			const next = collect({ shot: last, f: fields });
			if (holdBack(next)) return;
			void saveShot({ session, shot: next }).then(() => saved({ shot: next, quiet: true }));
		};
	}, [session]);

	// A finished rewrite lands in the form for review; nothing auto-commits.
	if (rewrite && rewrite !== appliedRewrite && rewrite.status !== "running") {
		setAppliedRewrite(rewrite);
		if (rewrite.status === "error") setAiStatus(`failed: ${rewrite.error}`);
		else if (rewrite.proposal) {
			const { next, changed } = applyProposal({ f, p: rewrite.proposal, shot });
			const c = rewrite.cost ? ` · $${Number(rewrite.cost).toFixed(3)}` : "";
			setF(next);
			if (changed.length) setIsDirty(true);
			setAiStatus(changed.length ? `proposed: ${changed.join(", ")}${c}. Review and save (Ctrl+S), or move on to keep it.` : `AI suggested no change${c}`);
		}
	}

	const startRewrite = async () => {
		const instruction = ai.trim();
		if (!instruction) return setAiStatus("describe what to change first");
		try {
			await post({ path: "/_plan/api/rewrite", body: { session, shot: collect({ shot, f }), instruction } });
			onRewriteStarted();
			setAiStatus("rewriting in background, keep editing other shots…");
		} catch (e) {
			setAiStatus(e instanceof Error ? e.message : "failed to start");
		}
	};

	const runCommand = async () => {
		const target = shot.shot_number;
		const text = cmd.trim();
		if (!text) return setCmdStatus("type a command first");
		if (isDirty && !(await save({ quiet: true }))) return;
		try {
			await post({ path: "/_plan/api/command", body: { session, shot: shot.shot_number, audio: shot.audio || "", text } });
		} catch (e) {
			return setCmdStatus(e instanceof Error ? e.message : "failed to start");
		}
		setCmdStatus("working…");
		const poll = async (): Promise<void> => {
			const d = await api<{ status: string; error?: string; cost?: number; result?: Shot }>(`/_plan/api/command?session=${encodeURIComponent(session)}`);
			if (d.status === "running") {
				await new Promise((r) => setTimeout(r, 1500));
				return poll();
			}
			if (d.status === "error") return setCmdStatus(`failed: ${d.error}`);
			const rr = d.result || {};
			const c = d.cost ? ` · $${Number(d.cost).toFixed(3)}` : "";
			const msg =
				rr.op === "split" ? `split at "${rr.at_word}" (${rr.at_time}s) → shots ${rr.into?.join(" + ")}` : rr.op === "merge" ? `merged ${rr.merged?.join(" + ")} → shot ${rr.into}` : rr.op === "overlay" ? `overlay added: "${rr.caption}"` : "done";
			onStatus(`${msg}${c}`);
			onCommandDone({ landOn: (Array.isArray(rr.into) ? rr.into[0] : rr.into) ?? null, target, viewedAt: viewedAt.current });
		};
		await new Promise((r) => setTimeout(r, 1500));
		await poll().catch((e) => setCmdStatus(String(e)));
	};

	const v = shot.visual || {};
	const dur = ((shot.end ?? 0) - (shot.start ?? 0)).toFixed(2);

	return (
		<div className="space-y-3 p-3" ref={box}>
			<div>
				<p className="text-base">{shot.audio || "—"}</p>
				<p className="text-muted-foreground text-xs">
					shot {shot.shot_number} · {dur}s spoken · timing is derived from the audio, not editable here
				</p>
			</div>
			<Section title="Visual">
				<Lbl text="Description (what the shot shows)">
					<textarea className={`${inputClass} min-h-12`} value={f.desc} onChange={set("desc")} />
				</Lbl>
				<div className="flex gap-2">
					<Lbl text="Type" className="w-44">
						<select className={inputClass} value={f.type} onChange={set("type")}>
							{["REAL_FOOTAGE", "REAL_IMAGE", "MOTION_GRAPHICS"].map((t) => (
								<option key={t}>{t}</option>
							))}
						</select>
					</Lbl>
					<Lbl text="Specificity" className="w-32">
						<select className={inputClass} value={f.spec} onChange={set("spec")}>
							{["low", "medium", "high"].map((t) => (
								<option key={t}>{t}</option>
							))}
						</select>
					</Lbl>
					<Lbl text="FX (comma-sep: zoom_in, slow_motion)" className="flex-1">
						<input className={inputClass} value={f.fx} onChange={set("fx")} />
					</Lbl>
				</div>
				<Lbl text="Search: one source per line, source: query, query">
					<textarea className={`${inputClass} min-h-12 font-mono text-xs`} value={f.queries} onChange={set("queries")} />
				</Lbl>
			</Section>
			<Section title="Audio layer">
				<Lbl text="Music bed (mood)">
					<input className={inputClass} value={f.music} onChange={set("music")} />
				</Lbl>
				<Lbl text="SFX, one per line: sound | word (word is optional, aligns to it)">
					<textarea className={`${inputClass} min-h-12 font-mono text-xs`} placeholder="record scratch | but" value={f.sfx} onChange={set("sfx")} />
				</Lbl>
			</Section>
			<Section title="Ask AI to rewrite this shot">
				<Lbl text="Describe the vibe: it rewrites the fields, you review and save (about $0.04, runs in background)">
					<textarea
						className={`${inputClass} min-h-12`}
						placeholder="e.g. make the desc punchier and more sarcastic; add a record-scratch sfx on 'but'"
						value={ai}
						onChange={(e) => setAi(e.target.value)}
					/>
				</Lbl>
				<div className="flex items-center gap-2">
					<Button size="sm" onClick={startRewrite} disabled={rewrite?.status === "running"}>
						Rewrite
					</Button>
					<span className="text-muted-foreground text-xs">{rewrite?.status === "running" ? "rewriting…" : aiStatus}</span>
				</div>
			</Section>
			<Section title="Structural edit (split / merge / overlay)">
				<Lbl text="Tell it what to do; timing comes from the real word timings (about $0.02)">
					<input
						className={inputClass}
						placeholder="split at the word 'had'  ·  merge with the next shot  ·  add an overlay saying 27 BACKTESTS"
						value={cmd}
						onChange={(e) => setCmd(e.target.value)}
					/>
				</Lbl>
				<div className="flex items-center gap-2">
					<Button size="sm" onClick={runCommand}>
						Apply
					</Button>
					<span className="text-muted-foreground text-xs">{cmdStatus}</span>
				</div>
			</Section>
			<Section title="Caption / overlay">
				<Lbl text="Caption text">
					<input className={inputClass} value={f.caption} onChange={set("caption")} />
				</Lbl>
				{shot.overlay && (
					<>
						<Lbl text="Overlay caption">
							<input className={inputClass} value={f.ocaption} onChange={set("ocaption")} />
						</Lbl>
						<Lbl text="Overlay desc">
							<textarea className={`${inputClass} min-h-12`} value={f.odesc} onChange={set("odesc")} />
						</Lbl>
					</>
				)}
			</Section>
			<Button size="sm" onClick={async () => (await save({ quiet: false })) && onSaveAndAdvance()}>
				Save shot
			</Button>
			<span className="text-muted-foreground ml-2 text-xs">{v.type}</span>
		</div>
	);
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
	return (
		<fieldset className="space-y-2 rounded-md border p-2.5">
			<legend className="text-muted-foreground px-1 text-[11px] uppercase">{title}</legend>
			{children}
		</fieldset>
	);
}

function Lbl({ text, className, children }: { text: string; className?: string; children: React.ReactNode }) {
	return (
		<label className={cn("block space-y-1", className)}>
			<span className="text-muted-foreground block text-[11px]">{text}</span>
			{children}
		</label>
	);
}
