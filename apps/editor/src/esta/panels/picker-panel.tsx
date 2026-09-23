"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/ui";
import { api, post } from "../api";
import { mediaUrl } from "../doc";
import { useWorkspace } from "../store";
import { inputClass } from "../ui";

// Port of v2 tools/picker/index.html. The human is the visual validator: a
// pick writes the same assets_progress.jsonl line the auto path writes.

type PickerShot = {
	shot_number: number;
	audio: string;
	desc: string;
	type: string;
	duration: number;
	queries: string[];
	sources: string[];
	has_candidates: boolean;
	generated: { file: string; flavor: string } | null;
	user_picked: boolean;
	picked: { source: string; file: string; url: string; ok: boolean } | null;
};
type Candidate = {
	candidate_id: string;
	generated?: boolean;
	source: string;
	asset_type: string;
	file: string;
	url: string;
	query: string;
	thumb?: string;
	width?: number | null;
	height?: number | null;
	in_point?: number;
	source_duration?: number;
};
type Manifest = { queries?: string[]; sources?: string[]; candidates?: Candidate[] };
type BankSource = { name: string; kind: string; available: boolean; unavailable_reason?: string };
type PickJob = { status: string; started: number; log?: string };

export function PickerPanel() {
	const { session, selectedShot, selectShot } = useWorkspace();
	const [shots, setShots] = useState<PickerShot[] | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [bank, setBank] = useState<BankSource[]>([]);
	const [jobs, setJobs] = useState<Record<string, PickJob>>({});
	const [log, setLog] = useState("");
	const q = encodeURIComponent(session);

	const loadShots = useCallback(
		() =>
			api<{ shots: PickerShot[] }>(`/_picker/api/shots?session=${q}`).then(
				(d) => {
					setShots(d.shots);
					setError(null);
					return d.shots;
				},
				(e) => {
					setError(e instanceof Error ? e.message : String(e));
					return null;
				},
			),
		[q],
	);

	// Bank first: the armed source set is seeded against it.
	useEffect(() => {
		api<{ sources: BankSource[] }>(`/_picker/api/sources?session=${q}`)
			.then((d) => setBank(d.sources || []))
			.catch((e) => setLog(`could not load the source bank: ${e instanceof Error ? e.message : e}`))
			.finally(() => void loadShots());
	}, [q, loadShots]);

	useEffect(() => {
		if (shots?.length && !shots.some((s) => s.shot_number === selectedShot)) selectShot(shots[0].shot_number);
	}, [shots, selectedShot, selectShot]);

	// Fetches run server-side and outlive navigation; one poller keeps the rail current.
	const jobsRef = useRef(jobs);
	useEffect(() => {
		jobsRef.current = jobs;
	});
	const pollJobs = useCallback(async () => {
		const d = await api<{ jobs: Record<string, PickJob> }>(`/_picker/api/jobs?session=${q}`).catch(() => null);
		if (!d) return;
		const prev = jobsRef.current;
		const finished = Object.keys(prev).filter((n) => prev[n].status === "running" && d.jobs[n] && d.jobs[n].status !== "running");
		setJobs(d.jobs);
		if (!finished.length) return;
		void loadShots();
		const errs = finished.filter((n) => d.jobs[n].status === "error");
		setLog(errs.length ? `shot ${errs.join(", ")}: fetch failed\n${(d.jobs[errs[0]].log || "").slice(-1200)}` : `shot ${finished.join(", ")}: candidates ready`);
	}, [q, loadShots]);
	useEffect(() => void pollJobs(), [pollJobs]);
	const busy = Object.values(jobs).some((j) => j.status === "running");
	useEffect(() => {
		if (!busy) return;
		const t = setInterval(() => void pollJobs(), 1500);
		return () => clearInterval(t);
	}, [busy, pollJobs]);

	if (error) return <p className="text-muted-foreground p-3 text-sm">{error.includes("no plan.json") ? "No plan.json yet: the picker needs a plan." : error}</p>;
	if (!shots) return <p className="text-muted-foreground p-3 text-sm">Loading shots…</p>;
	const shot = shots.find((s) => s.shot_number === selectedShot) ?? null;

	const dotClass = (s: PickerShot) => {
		const j = jobs[String(s.shot_number)];
		if (j?.status === "running") return "bg-primary animate-pulse";
		if (s.picked?.ok) return "bg-constructive";
		if (j?.status === "error") return "bg-destructive";
		if (s.has_candidates) return "bg-caution";
		return "bg-muted";
	};

	return (
		<div className="flex size-full min-h-0 text-sm">
			<div className="w-60 shrink-0 overflow-auto border-r">
				<div className="text-muted-foreground sticky top-0 border-b bg-inherit px-2 py-1.5 text-xs uppercase">Shots</div>
				{shots.map((s) => (
					<button
						key={s.shot_number}
						type="button"
						onClick={() => selectShot(s.shot_number)}
						className={cn("flex w-full items-center gap-2 border-b px-2 py-1.5 text-left", s.shot_number === selectedShot ? "bg-accent" : "hover:bg-accent/50")}
					>
						<span className={cn("size-2 shrink-0 rounded-full", dotClass(s))} />
						<span className="text-muted-foreground w-6 shrink-0 text-right text-xs tabular-nums">{s.shot_number}</span>
						<span className="min-w-0 flex-1 truncate">{s.audio}</span>
					</button>
				))}
			</div>
			<div className="flex min-w-0 flex-1 flex-col">
				<div className="min-h-0 flex-1 overflow-auto p-3">
					{shot && (
						<ShotCandidates
							key={shot.shot_number}
							session={session}
							shot={shot}
							bank={bank}
							onFetchStarted={() => {
								setJobs((prev) => ({ ...prev, [String(shot.shot_number)]: { status: "running", started: Date.now() } }));
								setLog(`shot ${shot.shot_number}: fetching in background. Go pick something else; the dot turns green when it lands.`);
							}}
							fetchFinished={jobs[String(shot.shot_number)]?.status !== "running"}
							onLog={setLog}
							onPicked={async () => {
								const fresh = await loadShots();
								if (!fresh) return;
								// Advance to the next unpicked shot: the point is to keep moving.
								const next = fresh.find((s) => s.shot_number > shot.shot_number && !s.picked?.ok) || fresh.find((s) => !s.picked?.ok);
								selectShot(next ? next.shot_number : shot.shot_number);
							}}
						/>
					)}
				</div>
				{log && <pre className="bg-accent/40 max-h-32 shrink-0 overflow-auto border-t px-3 py-1.5 font-mono text-[11px] whitespace-pre-wrap">{log}</pre>}
			</div>
		</div>
	);
}

function ShotCandidates({
	session,
	shot,
	bank,
	onFetchStarted,
	fetchFinished,
	onLog,
	onPicked,
}: {
	session: string;
	shot: PickerShot;
	bank: BankSource[];
	onFetchStarted: () => void;
	fetchFinished: boolean;
	onLog: (s: string) => void;
	onPicked: () => void;
}) {
	const [manifest, setManifest] = useState<Manifest | null | undefined>(undefined);
	const [queries, setQueries] = useState<string | null>(null);
	const [armed, setArmed] = useState<Set<string> | null>(null);
	const [perSource, setPerSource] = useState(4);

	// Re-read candidates whenever a fetch for this shot lands.
	useEffect(() => {
		if (!fetchFinished) return;
		api<Manifest>(`/_picker/api/candidates?session=${encodeURIComponent(session)}&shot=${shot.shot_number}`).then(setManifest, () => setManifest(null));
	}, [session, shot.shot_number, fetchFinished]);

	// Seed from what this shot last searched, else the plan's prescription; drop unavailable sources.
	const avail = new Set(bank.filter((b) => b.available).map((b) => b.name));
	const seedSources = manifest?.sources?.length ? manifest.sources : shot.sources;
	const effArmed = armed ?? new Set((seedSources || []).filter((n) => !bank.length || avail.has(n)));
	const effQueries = queries ?? [...new Set(manifest?.queries?.length ? manifest.queries : shot.queries)].join(" | ");
	const prescribed = new Set(shot.sources);

	const refetch = async () => {
		if (!effArmed.size) return onLog("arm at least one source first.");
		try {
			await post({
				path: "/_picker/api/refetch",
				body: { session, shot: shot.shot_number, queries: effQueries, sources: [...effArmed].join(","), per_source: perSource || 4 },
			});
			onFetchStarted();
		} catch (e) {
			onLog(e instanceof Error ? e.message : "fetch failed to start");
		}
	};

	const pick = async (id: string) => {
		try {
			const d = await post<{ picked: { source: string; in_point: number; out_point: number }; cleaned: number; kept_shared: number }>({
				path: "/_picker/api/pick",
				body: { session, shot: shot.shot_number, candidate_id: id },
			});
			const shared = d.kept_shared ? `, ${d.kept_shared} kept (in use by another shot)` : "";
			onLog(`shot ${shot.shot_number} → ${d.picked.source} (${d.picked.in_point}s→${d.picked.out_point}s) · ${d.cleaned} losers deleted${shared}`);
			onPicked();
		} catch (e) {
			onLog(e instanceof Error ? e.message : "pick failed");
		}
	};

	const toggle = (name: string) => {
		const next = new Set(effArmed);
		if (next.has(name)) next.delete(name);
		else next.add(name);
		setArmed(next);
	};

	const pickedFile = shot.picked?.file?.replace(/\\/g, "/");
	// Generation and the stock fetch race on the feed; an auto-fetch that landed
	// on a graphic wasn't a choice, so say so (a deliberate pick is left alone).
	const overridden = shot.generated && pickedFile !== shot.generated.file && !shot.user_picked;

	return (
		<div className="space-y-3">
			<div>
				<p className="text-base">{shot.audio}</p>
				<p className="text-muted-foreground">{shot.desc}</p>
				<p className="text-muted-foreground text-xs tabular-nums">
					shot {shot.shot_number} · {shot.duration}s · {shot.type}
					{shot.picked?.ok && <span className="text-constructive"> · picked: {shot.picked.source}</span>}
				</p>
			</div>
			<fieldset className="space-y-2 rounded-md border p-2.5">
				<legend className="text-muted-foreground px-1 text-[11px] uppercase">Search</legend>
				<label className="block space-y-1">
					<span className="text-muted-foreground block text-[11px]">Queries, separated with |</span>
					<input className={inputClass} value={effQueries} onChange={(e) => setQueries(e.target.value)} />
				</label>
				<div className="text-muted-foreground text-[11px]">
					Sources: <span className="text-caution">*</span> = prescribed by the plan; click any to arm it
				</div>
				<div className="flex flex-wrap items-center gap-1.5">
					{bank.map((b) => {
						const on = effArmed.has(b.name);
						return (
							<button
								key={b.name}
								type="button"
								disabled={!b.available}
								title={b.available ? (prescribed.has(b.name) ? "prescribed by the plan" : "not in the plan, added by you") : `unavailable: ${b.unavailable_reason}`}
								onClick={() => toggle(b.name)}
								className={cn(
									"flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
									!b.available ? "cursor-not-allowed line-through opacity-40" : on ? "border-primary text-primary bg-primary/10" : "text-muted-foreground hover:bg-accent",
								)}
							>
								{prescribed.has(b.name) && <span className="text-caution">*</span>}
								{b.name}
								<span className="text-[9px] uppercase opacity-60">{b.kind}</span>
							</button>
						);
					})}
					<span className="text-muted-foreground ml-auto flex gap-2 text-[11px]">
						<button type="button" className="underline" onClick={() => setArmed(new Set(avail))}>
							all
						</button>
						<button type="button" className="underline" onClick={() => setArmed(new Set())}>
							none
						</button>
						<button type="button" className="underline" onClick={() => setArmed(new Set([...prescribed].filter((n) => avail.has(n))))}>
							plan only
						</button>
					</span>
				</div>
				<div className="flex items-end gap-2">
					<label className="block w-24 space-y-1">
						<span className="text-muted-foreground block text-[11px]">Per query</span>
						<input type="number" min={1} max={10} className={inputClass} value={perSource} onChange={(e) => setPerSource(Number(e.target.value))} />
					</label>
					<Button size="sm" onClick={refetch} disabled={!fetchFinished}>
						{fetchFinished ? "Fetch" : "Fetching…"}
					</Button>
				</div>
			</fieldset>
			{overridden && (
				<div className="rounded-md border border-violet-500/60 bg-violet-500/10 px-2.5 py-1.5 text-xs">
					<b className="text-violet-500">Generated graphic overridden:</b> an auto-fetch landed on top of this shot&apos;s motion graphic. Pick the <b>GENERATED</b> tile to put it back.
				</div>
			)}
			{manifest === undefined ? (
				<p className="text-muted-foreground text-xs">Loading candidates…</p>
			) : !manifest?.candidates?.length ? (
				<p className="text-muted-foreground text-xs">No candidates yet. Hit Fetch.</p>
			) : (
				<Grid candidates={manifest.candidates} pickedFile={pickedFile} onPick={pick} />
			)}
		</div>
	);
}

// At most ONE <video> exists at a time, created on hover: decoding the whole
// grid of 1080p stock at once pinned the CPU in v2.
function Grid({ candidates, pickedFile, onPick }: { candidates: Candidate[]; pickedFile: string | undefined; onPick: (id: string) => void }) {
	const [live, setLive] = useState<string | null>(null);
	const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
	return (
		<div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
			{candidates.map((c) => {
				const u = mediaUrl(c.url);
				const chosen = Boolean(pickedFile) && c.file === pickedFile;
				const dims = c.width && c.height ? ` · ${c.width}×${c.height}` : "";
				return (
					<div key={c.candidate_id} className={cn("overflow-hidden rounded-md border-2 bg-black", chosen ? "border-constructive" : c.generated ? "border-violet-500" : "border-border")}>
						<div
							className="relative aspect-[9/16] w-full"
							onMouseEnter={() => {
								if (c.asset_type !== "video") return;
								// Small delay so sweeping across the grid doesn't spawn a decoder per tile.
								timer.current = setTimeout(() => setLive(c.candidate_id), 120);
							}}
							onMouseLeave={() => {
								if (timer.current) clearTimeout(timer.current);
								setLive((cur) => (cur === c.candidate_id ? null : cur));
							}}
						>
							{live === c.candidate_id ? (
								<video className="absolute inset-0 size-full object-contain" src={`${u}#t=${c.in_point || 0}`} muted loop playsInline autoPlay preload="auto">
									<track kind="captions" />
								</video>
							) : c.asset_type === "video" ? (
								<>
									{c.thumb && (
										// eslint-disable-next-line @next/next/no-img-element
										<img className="absolute inset-0 size-full object-contain" src={c.thumb} alt="" loading="lazy" referrerPolicy="no-referrer" />
									)}
									<span className="absolute inset-0 flex items-center justify-center text-[11px] text-neutral-500">hover to play</span>
								</>
							) : (
								// eslint-disable-next-line @next/next/no-img-element
								<img className="absolute inset-0 size-full object-contain" src={u} alt="" loading="lazy" />
							)}
						</div>
						<div className="bg-card text-muted-foreground px-2 py-1.5 text-[11px]">
							{c.generated && <span className="mr-1 rounded bg-violet-500 px-1 text-[9px] font-bold text-white">GENERATED</span>}
							<b className="text-foreground">{c.source}</b>
							{dims}
							{c.source_duration ? ` · ${c.source_duration.toFixed(1)}s` : ""}
							<br />
							{c.query}
						</div>
						<div className="bg-card flex gap-1.5 px-2 pb-2">
							<Button size="sm" className="flex-1" onClick={() => onPick(c.candidate_id)}>
								{chosen ? "Picked" : "Use this"}
							</Button>
							<Button size="sm" variant="outline" className="flex-1" onClick={() => window.open(u, "_blank")}>
								Open
							</Button>
						</div>
					</div>
				);
			})}
		</div>
	);
}
