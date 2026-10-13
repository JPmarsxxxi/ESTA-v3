"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/ui";
import { readSelection, selectionBlock, selectionLabel, useTimelineSelection } from "../opencut/selection";
import { useWorkspace } from "../store";
import { inputClass } from "../ui";

// A real headless Claude Code session in the repo: same skills, CLAUDE.md and
// MCP servers as the terminal.
export function ChatPanel() {
	const { chat, chatId, sendChat, restartChat, interruptChat } = useWorkspace();
	const [text, setText] = useState("");
	const [error, setError] = useState<string | null>(null);
	const scrollRef = useRef<HTMLDivElement>(null);
	// The chip follows the live timeline selection; removing it detaches that selection only.
	const selection = useTimelineSelection();
	const [dismissed, setDismissed] = useState<string | null>(null);
	const label = selection.key !== dismissed ? selectionLabel(selection) : null;

	useEffect(() => {
		const el = scrollRef.current;
		if (el) el.scrollTop = el.scrollHeight;
	}, [chat.items]);

	const send = async () => {
		const t = text.trim();
		if (!t) return;
		setError(null);
		try {
			// The selection at the moment of sending, with fresh in/out points.
			const now = readSelection();
			await sendChat({ text: t, selection: (now.clips.length || now.track) && now.key !== dismissed ? selectionBlock(now) : undefined });
			setText("");
		} catch (e) {
			setError(e instanceof Error ? e.message : String(e));
		}
	};

	return (
		<div className="flex size-full min-h-0 flex-col text-sm">
			{chatId && !chat.alive && (
				<div className="bg-caution/15 flex shrink-0 items-center justify-between gap-2 px-2 py-1.5 text-xs">
					<span>Chat disconnected: the Claude process exited.</span>
					<Button size="sm" variant="outline" onClick={() => restartChat()}>
						Restart chat
					</Button>
				</div>
			)}
			<div ref={scrollRef} className="min-h-0 flex-1 space-y-2 overflow-auto p-2">
				{chat.items.length === 0 && (
					<p className="text-muted-foreground text-xs">
						Ask anything: &quot;what runs next?&quot;, &quot;tighten the hook&quot;, &quot;redo line L04 angrier&quot;. Every message carries this session and stage. Claude starts with your first message.
					</p>
				)}
				{chat.items.map((item, i) => {
					if (item.kind === "user")
						return (
							<div key={i} className="bg-accent ml-8 rounded-md px-2.5 py-1.5 whitespace-pre-wrap">
								{item.selection && (
									<div className="text-muted-foreground mb-1 truncate text-[11px]" title={item.selection}>
										with selection: {item.selection}
									</div>
								)}
								{item.text}
							</div>
						);
					if (item.kind === "assistant")
						return item.streaming ? (
							<div key={i} className="mr-4 whitespace-pre-wrap opacity-80">
								{item.text}
							</div>
						) : (
							<div key={i} className="prose prose-sm dark:prose-invert mr-4 max-w-none text-sm [&_table]:text-xs">
								<ReactMarkdown remarkPlugins={[remarkGfm]}>{item.text}</ReactMarkdown>
							</div>
						);
					if (item.kind === "tool")
						return (
							<div key={i} className="text-muted-foreground truncate font-mono text-[11px]" title={item.input}>
								› {item.name} {item.input}
							</div>
						);
					if (item.kind === "result")
						return (
							<div key={i} className={cn("text-muted-foreground text-[11px]", item.error && "text-destructive")}>
								{item.error ? "turn failed" : "done"}
								{item.cost != null ? ` · $${item.cost.toFixed(3)}` : ""}
							</div>
						);
					return (
						<div key={i} className="text-caution text-xs">
							{item.text}
						</div>
					);
				})}
			</div>
			{error && <div className="text-destructive shrink-0 px-2 text-xs">{error}</div>}
			{label && (
				<div className="flex shrink-0 items-center gap-1 border-t px-2 pt-1.5">
					<span className="bg-primary/15 text-primary flex max-w-full items-center gap-1 rounded-full py-0.5 pr-1 pl-2 text-xs">
						<span className="truncate">{label}</span>
						<button type="button" aria-label="Don't send the selection" className="hover:bg-primary/20 rounded-full px-1" onClick={() => setDismissed(selection.key)}>
							×
						</button>
					</span>
				</div>
			)}
			<div className={cn("flex shrink-0 gap-1.5 p-2", !label && "border-t")}>
				<textarea
					className={`${inputClass} min-h-9 resize-none`}
					rows={2}
					value={text}
					placeholder={chatId && !chat.alive ? "Chat is disconnected" : label ? `What should Claude do with ${label}?` : "Message Claude…"}
					disabled={Boolean(chatId) && !chat.alive}
					onChange={(e) => setText(e.target.value)}
					onKeyDown={(e) => {
						if (e.key === "Enter" && !e.shiftKey) {
							e.preventDefault();
							send();
						}
					}}
				/>
				{chat.busy ? (
					<Button size="sm" variant="outline" onClick={() => interruptChat()}>
						Stop
					</Button>
				) : (
					<Button size="sm" disabled={(Boolean(chatId) && !chat.alive) || !text.trim()} onClick={send}>
						Send
					</Button>
				)}
			</div>
		</div>
	);
}
