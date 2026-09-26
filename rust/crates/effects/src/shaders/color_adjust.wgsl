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

// scalars: brightness (-1..1, added), contrast and saturation (-1..1, as
// 1 + value multipliers), hue (degrees). Alpha is straight, so only rgb moves.
@fragment
fn fragment_main(input: VertexOutput) -> @location(0) vec4f {
    let color = textureSample(input_texture, input_sampler, input.tex_coord);
    var rgb = color.rgb + vec3f(uniforms.scalars.x);
    rgb = (rgb - vec3f(0.5)) * (1.0 + uniforms.scalars.y) + vec3f(0.5);
    let luma = dot(rgb, vec3f(0.2126, 0.7152, 0.0722));
    rgb = mix(vec3f(luma), rgb, 1.0 + uniforms.scalars.z);
    // Hue: rotate around the grey axis (Rodrigues).
    let angle = radians(uniforms.scalars.w);
    let axis = vec3f(0.57735027);
    rgb = rgb * cos(angle) + cross(axis, rgb) * sin(angle) + axis * dot(axis, rgb) * (1.0 - cos(angle));
    return vec4f(clamp(rgb, vec3f(0.0), vec3f(1.0)), color.a);
}
