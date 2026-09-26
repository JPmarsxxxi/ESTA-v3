import type { ElementParamDefinition } from "@/params/registry";

// OpenCut text has no outline or drop shadow; captions over busy footage need
// both. Sizes are percent of the font size so they follow font-size changes.
export const OUTLINE = { width: "esta.outline.width", color: "esta.outline.color" } as const;
export const SHADOW = {
	enabled: "esta.shadow.enabled",
	color: "esta.shadow.color",
	opacity: "esta.shadow.opacity",
	blur: "esta.shadow.blur",
	offsetX: "esta.shadow.offsetX",
	offsetY: "esta.shadow.offsetY",
} as const;

const onShadow = [{ param: SHADOW.enabled, equals: true }];

export const TEXT_STYLE_PARAMS: ElementParamDefinition[] = [
	{ key: OUTLINE.width, label: "Outline Width", type: "number", default: 0, min: 0, max: 50, step: 1 },
	{ key: OUTLINE.color, label: "Outline Color", type: "color", default: "#000000" },
	{ key: SHADOW.enabled, label: "Shadow Enabled", type: "boolean", default: false, keyframable: false },
	{ key: SHADOW.color, label: "Shadow Color", type: "color", default: "#000000", dependencies: onShadow },
	{ key: SHADOW.opacity, label: "Shadow Opacity", type: "number", default: 80, min: 0, max: 100, step: 1, dependencies: onShadow },
	{ key: SHADOW.blur, label: "Shadow Blur", type: "number", default: 15, min: 0, max: 200, step: 1, dependencies: onShadow },
	{ key: SHADOW.offsetX, label: "Shadow Offset X", type: "number", default: 4, min: -200, max: 200, step: 1, dependencies: onShadow },
	{ key: SHADOW.offsetY, label: "Shadow Offset Y", type: "number", default: 6, min: -200, max: 200, step: 1, dependencies: onShadow },
];
export const TEXT_STYLE_KEYS = TEXT_STYLE_PARAMS.map((p) => p.key);

