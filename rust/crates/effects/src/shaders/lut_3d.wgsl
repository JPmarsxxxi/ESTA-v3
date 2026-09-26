struct VertexOutput {
    @builtin(position) position: vec4f,
    @location(0) tex_coord: vec2f,
}

struct EffectUniforms {
    resolution: vec2f,
    direction: vec2f,
    scalars: vec4f,
}

@group(0) @binding(0) var input_texture: texture_2d<f32>;
@group(0) @binding(1) var input_sampler: sampler;
@group(1) @binding(0) var<uniform> uniforms: EffectUniforms;
@group(2) @binding(0) var lut_texture: texture_2d<f32>;
@group(2) @binding(1) var lut_sampler: sampler;

// scalars: LUT size (points per axis), intensity (0..1). The 3D LUT is `size`
// slices of size x size laid side by side (x = red + blue * size, y = green):
// the sampler interpolates red and green within a slice, blue is mixed between
// the two nearest slices by hand. Alpha is straight, so only rgb moves.
@fragment
fn fragment_main(input: VertexOutput) -> @location(0) vec4f {
    let color = textureSample(input_texture, input_sampler, input.tex_coord);
    let size = uniforms.scalars.x;
    let c = clamp(color.rgb, vec3f(0.0), vec3f(1.0)) * (size - 1.0);
    let b0 = floor(c.b);
    let b1 = min(b0 + 1.0, size - 1.0);
    let y = (c.g + 0.5) / size;
    let lo = textureSample(lut_texture, lut_sampler, vec2f((b0 * size + c.r + 0.5) / (size * size), y)).rgb;
    let hi = textureSample(lut_texture, lut_sampler, vec2f((b1 * size + c.r + 0.5) / (size * size), y)).rgb;
    let graded = mix(lo, hi, c.b - b0);
    return vec4f(mix(color.rgb, graded, uniforms.scalars.y), color.a);
}
