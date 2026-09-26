import type { ComponentType } from "react";
import type { ParamDefinition, ParamValues } from "@/params";

export interface Effect {
	id: string;
	type: string;
	params: ParamValues;
	enabled: boolean;
}

export type EffectUniformValue = number | number[];

export interface EffectPass {
	shader: string;
	uniforms: Record<string, EffectUniformValue>;
	/** Id of a lookup-table texture the shader samples (see esta/opencut/grade.ts). */
	lut?: string;
}

/** A definition's own editor, shown under its generic param fields. */
export type EffectPanelProps = {
	params: ParamValues;
	preview: ({ key, value }: { key: string; value: number | string | boolean }) => void;
	commit: () => void;
};

export interface EffectPassTemplate {
	shader: string;
	uniforms(params: {
		effectParams: ParamValues;
		width: number;
		height: number;
	}): Record<string, EffectUniformValue>;
}

export interface EffectRendererConfig {
	passes: EffectPassTemplate[];
	buildPasses?: (params: {
		effectParams: ParamValues;
		width: number;
		height: number;
	}) => EffectPass[];
}

export interface EffectDefinition {
	type: string;
	name: string;
	keywords: string[];
	params: ParamDefinition[];
	renderer: EffectRendererConfig;
	panel?: ComponentType<EffectPanelProps>;
}
