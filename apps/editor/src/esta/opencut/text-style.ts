import { resolveAnimationPathValueAtTime } from "@/animation/resolve";
import type { TextElement } from "@/timeline";
import { drawMeasuredTextLayout, type MeasuredTextLayout, strokeMeasuredTextLayout } from "@/text/primitives";
import { TICKS_PER_SECOND } from "@/wasm";
import { drawKaraokeText, karaokeFits, karaokeOf } from "./karaoke";
import { OUTLINE, SHADOW, TEXT_STYLE_PARAMS } from "./text-style-params";

type Ctx = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

// Replaces OpenCut's single drawMeasuredTextLayout call: background, then
// shadow, outline and fill, with the fill word-by-word for karaoke captions.
export function drawStyledText({
	ctx,
	element,
	layout,
	textColor,
	backgroundColor,
	background,
	localTime,
	scale,
	textBaseline,
}: {
	ctx: Ctx;
	element: TextElement;
	layout: MeasuredTextLayout;
	textColor: string;
	backgroundColor: string;
	background: Parameters<typeof drawMeasuredTextLayout>[0]["background"];
	localTime: number;
	scale: number;
	textBaseline: CanvasTextBaseline;
}) {
	const params = element.params;
	const num = (key: string) => {
		const def = TEXT_STYLE_PARAMS.find((p) => p.key === key);
		const base = typeof params[key] === "number" ? params[key] : typeof def?.default === "number" ? def.default : 0;
		return resolveAnimationPathValueAtTime({ animations: element.animations, propertyPath: key, localTime: Math.max(0, localTime), fallbackValue: base });
	};
	const color = (key: string) =>
		resolveAnimationPathValueAtTime({ animations: element.animations, propertyPath: key, localTime: Math.max(0, localTime), fallbackValue: typeof params[key] === "string" ? params[key] : "#000000" });
	const em = (percent: number) => (percent / 100) * layout.scaledFontSize;

	drawMeasuredTextLayout({ ctx, layout, textColor: "transparent", background, backgroundColor, textBaseline });

	const outlineWidth = em(num(OUTLINE.width));
	// strokeText centres the line on the glyph edge; half of it sits under the fill.
	const outline = outlineWidth > 0 ? { color: color(OUTLINE.color), width: outlineWidth * 2 } : null;

	if (params[SHADOW.enabled] === true) {
		const shadowColor = color(SHADOW.color);
		const blur = em(num(SHADOW.blur)) * Math.abs(scale);
		ctx.save();
		ctx.globalAlpha *= Math.min(1, Math.max(0, num(SHADOW.opacity) / 100));
		if (blur > 0) ctx.filter = `blur(${blur / 2}px)`;
		ctx.translate(em(num(SHADOW.offsetX)), em(num(SHADOW.offsetY)));
		if (outline) strokeMeasuredTextLayout({ ctx, layout, strokeColor: shadowColor, strokeWidth: outline.width, textBaseline });
		drawMeasuredTextLayout({ ctx, layout, textColor: shadowColor, textBaseline });
		ctx.restore();
	}

	const karaoke = karaokeOf(params);
	if (karaoke && karaokeFits({ layout, karaoke })) {
		drawKaraokeText({ ctx, layout, karaoke, time: localTime / TICKS_PER_SECOND, textColor, textBaseline, outline });
		return;
	}
	if (outline) strokeMeasuredTextLayout({ ctx, layout, strokeColor: outline.color, strokeWidth: outline.width, textBaseline });
	drawMeasuredTextLayout({ ctx, layout, textColor, textBaseline });
}
