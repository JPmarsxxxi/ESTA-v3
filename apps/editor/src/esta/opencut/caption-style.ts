// The inspo's caption layer applied to render's caption blocks (SPEC.md Part 12, goal D). Profiling reads the
// inspo's captions (font class, colours, case, band); render and from_openreel.py carry them here as
// `captionStyle`. Null means no inspo was read for captions: the blocks keep today's style.
import { OUTLINE } from "./text-style-params";

export type CaptionStyle =
	| { present: false }
	| {
			present: true;
			fontClass: "serif" | "sans" | "condensed" | "display" | "mono" | string;
			colour: string;
			highlight?: string | null;
			case: "upper" | "lower" | "title" | "sentence" | string;
			band?: { y0: number; y1: number } | null;
			animation?: string;
	  };

export type CaptionBlock = {
	content: string;
	params: Record<string, string | number | boolean>;
	words?: [number, number][];
	highlight?: string | null;
};

// One Google font per class, all loadable by the editor's font atlas.
export const FONT_FOR_CLASS: Record<string, string> = {
	serif: "Playfair Display",
	sans: "Inter",
	condensed: "Anton",
	display: "Bangers",
	mono: "JetBrains Mono",
};

function applyCase({ text, mode }: { text: string; mode: string }): string {
	if (mode === "upper") return text.toUpperCase();
	if (mode === "lower") return text.toLowerCase();
	if (mode === "title") return text.replace(/\b\p{L}/gu, (c) => c.toUpperCase());
	return text;
}

export function captionsShown(style: CaptionStyle | null | undefined): boolean {
	return style?.present !== false;
}

export function styleCaption<T extends CaptionBlock>({ block, style, canvas }: { block: T; style: CaptionStyle | null | undefined; canvas: { height: number } }): T {
	if (!style || !style.present) return block;
	const params: CaptionBlock["params"] = {
		...block.params,
		fontFamily: FONT_FOR_CLASS[style.fontClass] ?? FONT_FOR_CLASS.sans,
		color: style.colour,
		// The inspo's captions sit straight on the picture: no box, an outline for legibility instead.
		"background.enabled": false,
		[OUTLINE.width]: 8,
		[OUTLINE.color]: "#000000",
	};
	if (style.band) params["transform.positionY"] = Math.round(((style.band.y0 + style.band.y1) / 2 - 0.5) * canvas.height);
	return { ...block, content: applyCase({ text: block.content, mode: style.case }), params, highlight: style.highlight ?? block.highlight };
}
