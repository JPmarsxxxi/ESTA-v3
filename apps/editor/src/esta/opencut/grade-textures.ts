import type { FrameItemDescriptor, TextureUploadDescriptor } from "@/services/renderer/compositor/types";
import { LUT_SIZE, gradePixels } from "./grade";

// The lookup tables a frame's effect passes name, as textures to upload
// alongside the layers. Their pixels never change for an id, so the id is the hash.
export function lutTextures(items: FrameItemDescriptor[]): TextureUploadDescriptor[] {
	const ids = new Set(items.flatMap((item) => item.effectPassGroups.flat().flatMap((pass) => (pass.lut ? [pass.lut] : []))));
	return [...ids].flatMap((id) => {
		const pixels = gradePixels(id);
		if (!pixels) return [];
		const width = LUT_SIZE * LUT_SIZE;
		return [{ kind: "rendered" as const, id, contentHash: id, width, height: LUT_SIZE, draw: (ctx) => ctx.putImageData(new ImageData(pixels, width, LUT_SIZE), 0, 0) }];
	});
}
