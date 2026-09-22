import type { ReactNode } from "react";
import type { Badge } from "./api";
import { cn } from "@/utils/ui";

export const inputClass =
	"border-border bg-background focus-visible:ring-ring w-full rounded-md border px-3 py-1.5 text-sm focus-visible:outline-hidden focus-visible:ring-1";

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
	return (
		<label className="block space-y-1">
			<span className="text-sm font-medium">{label}</span>
			{children}
			{error ? <span className="text-destructive block text-xs">{error}</span> : hint ? <span className="text-muted-foreground block text-xs">{hint}</span> : null}
		</label>
	);
}

const BADGE: Record<Badge, { dot: string; label: string }> = {
	idle: { dot: "bg-muted-foreground/40", label: "idle" },
	running: { dot: "bg-primary animate-pulse", label: "running" },
	failed: { dot: "bg-destructive", label: "failed" },
	done: { dot: "bg-constructive", label: "done" },
	overridden: { dot: "bg-caution", label: "overridden" },
	locked: { dot: "bg-muted-foreground/20 ring-1 ring-muted-foreground/50", label: "locked" },
	review: { dot: "bg-violet-500", label: "needs approval" },
	skipped: { dot: "bg-muted-foreground/20", label: "skipped" },
	"not-in-flow": { dot: "bg-transparent ring-1 ring-muted-foreground/30", label: "not in flow" },
};

export function BadgeDot({ badge, className }: { badge: Badge; className?: string }) {
	return <span title={BADGE[badge].label} className={cn("inline-block size-2.5 shrink-0 rounded-full", BADGE[badge].dot, className)} />;
}

export const badgeLabel = (b: Badge) => BADGE[b].label;

export function PanelShell({ title, controls, children }: { title: ReactNode; controls?: ReactNode; children: ReactNode }) {
	return (
		<div className="bg-card flex size-full min-h-0 flex-col overflow-hidden rounded-sm border">
			<div className="flex h-9 shrink-0 items-center justify-between gap-2 border-b px-2 text-sm">
				<div className="flex min-w-0 items-center gap-2">{title}</div>
				<div className="flex shrink-0 items-center gap-1">{controls}</div>
			</div>
			<div className="min-h-0 flex-1 overflow-auto">{children}</div>
		</div>
	);
}
