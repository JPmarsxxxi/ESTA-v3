use std::collections::HashMap;

#[derive(Clone, Debug)]
pub struct EffectPass {
    pub shader: String,
    pub uniforms: HashMap<String, UniformValue>,
    /// A lookup table the shader samples at group 2 (the `lut-3d` shader's
    /// 3D LUT, laid out as `size` slices of size x size side by side).
    pub lut: Option<wgpu::Texture>,
}

#[derive(Clone, Debug)]
pub enum UniformValue {
    Number(f32),
    Vector(Vec<f32>),
}
