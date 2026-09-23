"use client";

import { useCallback, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { ArrowDown, ArrowUp, CornerDownLeft, Pencil, Trash2, X } from "lucide-react";
import { cn } from "@/utils/ui";

// Port of v2 apps/studio LineEditor: a controlled editor over string[].
// select (click / shift / ctrl), double-click to edit, move the selection,
// delete it, or quote it into a chat instruction. The parent owns persistence.

// Move the selected lines (gathered into one block) by delta.
function moveLines({ lines, selected, delta }: { lines: string[]; selected: number[]; delta: -1 | 1 }) {
	if (selected.length === 0) return { lines, newSelected: selected };
	const sel = new Set(selected);
	const moving = [...selected].sort((a, b) => a - b).map((i) => lines[i]);
	const rest = lines.filter((_, i) => !sel.has(i));
	const firstIdx = Math.min(...selected);
	const precedingKept = lines.slice(0, firstIdx).filter((_, i) => !sel.has(i)).length;
	const insertAt = Math.max(0, Math.min(rest.length, precedingKept + delta));
	return { lines: [...rest.slice(0, insertAt), ...moving, ...rest.slice(insertAt)], newSelected: moving.map((_, k) => insertAt + k) };
}

export function LineEditor({
	lines,
	onChange,
	onInstruct,
	isHeader,
	renderLine,
	showBlanks = true,
	saving = false,
	extraActions,
}: {
	lines: string[];
	onChange: (lines: string[]) => void;
	onInstruct?: (text: string) => void;
	isHeader?: (line: string) => boolean;
	renderLine?: (line: string) => ReactNode;
	showBlanks?: boolean;
	saving?: boolean;
	extraActions?: (selected: number[]) => ReactNode;
}) {
	const [selected, setSelected] = useState<Set<number>>(new Set());
	const [editing, setEditing] = useState<number | null>(null);
	const [draft, setDraft] = useState("");
	const [instruction, setInstruction] = useState("");
	const anchor = useRef<number | null>(null);
	const selectedSorted = [...selected].sort((a, b) => a - b);

	const clickRow = useCallback(
		({ i, e }: { i: number; e: MouseEvent }) => {
			if (editing !== null) return;
			setSelected((prev) => {
				const next = new Set(prev);
				if (e.shiftKey && anchor.current !== null) {
					const [lo, hi] = [anchor.current, i].sort((a, b) => a - b);
					next.clear();
					for (let k = lo; k <= hi; k++) next.add(k);
				} else if (e.ctrlKey || e.metaKey) {
					if (next.has(i)) next.delete(i);
					else next.add(i);
					anchor.current = i;
				} else {
					next.clear();
					next.add(i);
					anchor.current = i;
				}
				return next;
			});
		},
		[editing],
	);

	const startEdit = (i: number) => {
		setEditing(i);
		setDraft(lines[i]);
	};

	const commitEdit = () => {
		if (editing === null) return;
		if (draft !== lines[editing]) {
			const next = lines.slice();
			next[editing] = draft;
			onChange(next);
		}
		setEditing(null);
	};

	const move = (delta: -1 | 1) => {
		const { lines: next, newSelected } = moveLines({ lines, selected: selectedSorted, delta });
		onChange(next);
		setSelected(new Set(newSelected));
		anchor.current = newSelected[0] ?? null;
	};

	const removeSelected = () => {
		if (!selected.size) return;
		onChange(lines.filter((_, i) => !selected.has(i)));
		setSelected(new Set());
		anchor.current = null;
	};

	const instruct = () => {
		const text = instruction.trim();
		if (!text || !selected.size || !onInstruct) return;
		onInstruct(`${text}\n\n--- lines ---\n${selectedSorted.map((i) => lines[i]).join("\n")}`);
		setInstruction("");
	};

	return (
		<div className="space-y-2">
			{selected.size > 0 && (
				<div className="bg-card sticky top-0 z-10 space-y-2 rounded-md border p-2">
					<div className="flex items-center gap-1">
						<span className="text-muted-foreground flex-1 text-xs">
							{selected.size} line{selected.size === 1 ? "" : "s"} selected
						</span>
						{extraActions?.(selectedSorted)}
						<IconBtn title="Move up" onClick={() => move(-1)}>
							<ArrowUp size={13} />
						</IconBtn>
						<IconBtn title="Move down" onClick={() => move(1)}>
							<ArrowDown size={13} />
						</IconBtn>
						<IconBtn title="Delete lines" onClick={removeSelected}>
							<Trash2 size={13} />
						</IconBtn>
						<IconBtn
							title="Clear selection"
							onClick={() => {
								setSelected(new Set());
								anchor.current = null;
							}}
						>
							<X size={13} />
						</IconBtn>
					</div>
					{onInstruct && (
						<div className="flex items-center gap-1.5">
							<Pencil size={11} className="text-muted-foreground shrink-0" />
							<input
								value={instruction}
								onChange={(e) => setInstruction(e.target.value)}
								onKeyDown={(e) => {
									if (e.key === "Enter") {
										e.preventDefault();
										instruct();
									}
								}}
								placeholder="tell Claude what to do with these lines…"
								className="min-w-0 flex-1 border-b bg-transparent py-0.5 text-xs outline-none"
							/>
							{instruction.trim() && (
								<IconBtn title="Send to chat" onClick={instruct}>
									<CornerDownLeft size={12} />
								</IconBtn>
							)}
						</div>
					)}
				</div>
			)}
			<div className="space-y-px">
				{lines.map((line, i) => {
					const isSel = selected.has(i);
					if (editing === i) {
						return (
							<textarea
								key={i}
								// eslint-disable-next-line jsx-a11y/no-autofocus
								autoFocus
								value={draft}
								onChange={(e) => setDraft(e.target.value)}
								onBlur={commitEdit}
								onKeyDown={(e) => {
									if (e.key === "Enter" && !e.shiftKey) {
										e.preventDefault();
										commitEdit();
									}
									if (e.key === "Escape") {
										e.preventDefault();
										setEditing(null);
									}
								}}
								rows={Math.max(1, Math.ceil(draft.length / 60))}
								className="border-primary/50 bg-background w-full resize-none rounded border px-2 py-1 text-sm outline-none"
							/>
						);
					}
					if (line.trim() === "" && showBlanks) {
						return (
							<button
								key={i}
								type="button"
								aria-label="blank line"
								onClick={(e) => clickRow({ i, e })}
								className={cn("block h-3 w-full rounded border-l-2", isSel ? "border-primary bg-primary/10" : "hover:bg-accent/40 border-transparent")}
							/>
						);
					}
					const header = isHeader?.(line);
					return (
						<div
							key={i}
							role="button"
							tabIndex={0}
							onClick={(e) => clickRow({ i, e })}
							onDoubleClick={() => startEdit(i)}
							onKeyDown={(e) => e.key === "Enter" && startEdit(i)}
							className={cn("group flex items-start gap-2 rounded border-l-2 px-2 py-1", isSel ? "border-primary bg-primary/10" : "hover:bg-accent/50 border-transparent")}
						>
							<span className={cn("min-w-0 flex-1 break-words", header ? "text-primary text-xs font-bold uppercase tracking-wide" : "text-sm leading-snug")}>
								{renderLine && !header ? renderLine(line) : line}
							</span>
							<button
								type="button"
								onClick={(e) => {
									e.stopPropagation();
									startEdit(i);
								}}
								className="text-muted-foreground hover:text-foreground shrink-0 opacity-0 group-hover:opacity-100"
								title="Edit line (or double-click)"
							>
								<Pencil size={11} />
							</button>
						</div>
					);
				})}
			</div>
			<div className="text-muted-foreground flex items-center justify-between px-1 text-[10px]">
				<span>Click to select · shift/ctrl-click for many · double-click to edit</span>
				{saving && <span className="text-primary">saving…</span>}
			</div>
		</div>
	);
}

function IconBtn({ title, onClick, children }: { title: string; onClick: () => void; children: ReactNode }) {
	return (
		<button type="button" title={title} onClick={onClick} className="hover:bg-accent text-muted-foreground hover:text-foreground rounded p-1">
			{children}
		</button>
	);
}
