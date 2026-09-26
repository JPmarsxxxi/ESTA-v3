import type { ParamValues } from "@/params";
import { setCanvasLetterSpacing } from "@/text/layout";
import type { MeasuredTextLayout } from "@/text/primitives";

// Render's captions are karaoke: word timings from faster-whisper, spoken words
// in the highlight colour, the current word filling left to right, upcoming
// words in the text colour (v2's caption-animation-renderer). A caption carries
// its timings in the `esta.karaoke` param, [start, end] per word in seconds
// from the caption's own start.
export const KARAOKE_PARAM = "esta.karaoke";
type Karaoke = { words: [number, number][]; highlight: string };

const ACTIVE_SCALE = 1.05;

export function karaokeOf(params: ParamValues): Karaoke | null {
	const raw = params[KARAOKE_PARAM];
	if (typeof raw !== "string") return null;
	try {
		const k: unknown = JSON.parse(raw);
		if (k && typeof k === "object" && "words" in k && Array.isArray(k.words) && "highlight" in k && typeof k.highlight === "string")
			return { words: k.words.filter((w): w is [number, number] => Array.isArray(w) && w.length === 2), highlight: k.highlight };
	} catch {
		/* not karaoke */
	}
	return null;
}

const wordsIn = (line: string) => [...line.matchAll(/\S+/g)];

// An edited caption whose words no longer line up with the timings is drawn plain.
export function karaokeFits({ layout, karaoke }: { layout: MeasuredTextLayout; karaoke: Karaoke }) {
	return layout.lines.reduce((n, line) => n + wordsIn(line).length, 0) === karaoke.words.length;
}

export function drawKaraokeText({
	ctx,
	layout,
	karaoke,
	time,
	textColor,
	textBaseline,
}: {
	ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;
	layout: MeasuredTextLayout;
	karaoke: Karaoke;
	time: number;
	textColor: string;
	textBaseline: CanvasTextBaseline;
}) {
	ctx.font = layout.fontString;
	ctx.textAlign = "left";
	ctx.textBaseline = textBaseline;
	setCanvasLetterSpacing({ ctx, letterSpacingPx: layout.letterSpacing });
	let index = 0;
	layout.lines.forEach((line, lineIndex) => {
		const y = lineIndex * layout.lineHeightPx - layout.block.visualCenterOffset;
		const width = layout.lineMetrics[lineIndex].width;
		const x0 = layout.textAlign === "center" ? -width / 2 : layout.textAlign === "right" ? -width : 0;
		for (const match of wordsIn(line)) {
			const [start, end] = karaoke.words[index++];
			const word = match[0];
			const x = x0 + ctx.measureText(line.slice(0, match.index)).width;
			if (time >= end || time < start) {
				ctx.fillStyle = time >= end ? karaoke.highlight : textColor;
				ctx.fillText(word, x, y);
				continue;
			}
			const w = ctx.measureText(word).width;
			const progress = Math.min(1, Math.max(0, (time - start) / Math.max(end - start, 0.001)));
			ctx.save();
			ctx.translate(x + w / 2, y);
			ctx.scale(ACTIVE_SCALE, ACTIVE_SCALE);
			ctx.fillStyle = textColor;
			ctx.fillText(word, -w / 2, 0);
			ctx.beginPath();
			ctx.rect(-w / 2, -layout.lineHeightPx, w * progress, layout.lineHeightPx * 2);
			ctx.clip();
			ctx.fillStyle = karaoke.highlight;
			ctx.fillText(word, -w / 2, 0);
			ctx.restore();
		}
	});
}
