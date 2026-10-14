import { expect, test } from "bun:test";
import { type CaptionBlock, FONT_FOR_CLASS, captionsShown, styleCaption } from "./caption-style";
import { OUTLINE } from "./text-style-params";

const block: CaptionBlock = { content: "the edge flipped", params: { fontFamily: "Anton", color: "#FFFFFF", "background.enabled": true, "transform.positionY": 422 }, words: [[0, 0.3], [0.3, 0.6], [0.6, 0.9]], highlight: "#fde047" };
const canvas = { height: 1920 };

test("the inspo's font class, colour, highlight, case and band replace today's style", () => {
	const out = styleCaption({ block, style: { present: true, fontClass: "serif", colour: "#3cdc5a", highlight: "#ffffff", case: "upper", band: { y0: 0.7, y1: 0.76 } }, canvas });
	expect(out.params.fontFamily).toBe(FONT_FOR_CLASS.serif);
	expect(out.params.color).toBe("#3cdc5a");
	expect(out.highlight).toBe("#ffffff");
	expect(out.content).toBe("THE EDGE FLIPPED");
	expect(out.params["transform.positionY"]).toBe(Math.round((0.73 - 0.5) * 1920));
	expect(out.params["background.enabled"]).toBe(false);
	expect(out.params[OUTLINE.width]).toBeGreaterThan(0);
	expect(out.words).toEqual(block.words);
});

test("each case and an unknown font class", () => {
	const style = (c: string) => ({ present: true as const, fontClass: "comic", colour: "#fff", case: c });
	expect(styleCaption({ block, style: style("title"), canvas }).content).toBe("The Edge Flipped");
	expect(styleCaption({ block: { ...block, content: "The Edge" }, style: style("lower"), canvas }).content).toBe("the edge");
	expect(styleCaption({ block, style: style("sentence"), canvas }).content).toBe("the edge flipped");
	expect(styleCaption({ block, style: style("upper"), canvas }).params.fontFamily).toBe(FONT_FOR_CLASS.sans);
	expect(styleCaption({ block, style: style("upper"), canvas }).params["transform.positionY"]).toBe(422);
});

test("no inspo style keeps today's captions; present false shows none", () => {
	expect(styleCaption({ block, style: null, canvas })).toBe(block);
	expect(captionsShown(null)).toBe(true);
	expect(captionsShown({ present: true, fontClass: "sans", colour: "#fff", case: "upper" })).toBe(true);
	expect(captionsShown({ present: false })).toBe(false);
});
