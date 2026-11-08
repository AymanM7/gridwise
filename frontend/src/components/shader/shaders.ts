/**
 * GLSL fragment shaders (WebGL1 / GLSL ES 1.0).
 * Shared uniforms: u_res, u_time, u_mouse (see ShaderCanvas). u_tint = strain color (rgb 0..1).
 */

const NOISE = `
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
             mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
  for (int i = 0; i < 5; i++) { v += a * noise(p); p = m * p; a *= 0.5; }
  return v;
}
`;

/**
 * Page background: slow domain-warped "energy field" (deep navy → teal), an aurora band at the top
 * tinted by tomorrow's peak strain, a soft glow that follows the pointer, vignette and film grain.
 */
export const AURORA_FRAG = `
precision highp float;
uniform vec2 u_res;
uniform float u_time;
uniform vec2 u_mouse;
uniform vec3 u_tint;
${NOISE}
void main() {
  vec2 uv = gl_FragCoord.xy / u_res;
  vec2 p = (gl_FragCoord.xy - 0.5 * u_res) / u_res.y;
  float t = u_time * 0.035;

  vec2 q = vec2(fbm(p * 1.3 + t), fbm(p * 1.3 - t + 5.2));
  vec2 r = vec2(fbm(p * 1.7 + 4.0 * q + vec2(1.7, 9.2) + 1.5 * t),
                fbm(p * 1.7 + 4.0 * q + vec2(8.3, 2.8) - t));
  float f = fbm(p * 1.1 + 3.0 * r);

  vec3 deep = vec3(0.010, 0.013, 0.024);
  vec3 teal = vec3(0.035, 0.20, 0.32);
  vec3 col = mix(deep, teal, smoothstep(0.35, 0.95, f) * 0.55);
  col = mix(col, u_tint * 0.55, smoothstep(0.75, 1.25, length(r)) * 0.35);

  // aurora curtain across the top
  float wave = 0.06 * sin(p.x * 2.2 + u_time * 0.25) + 0.035 * sin(p.x * 5.1 - u_time * 0.4);
  float band = exp(-pow((uv.y - 0.86 - wave) * 5.0, 2.0));
  vec3 aur = mix(vec3(0.20, 0.75, 0.95), u_tint, 0.55 + 0.45 * sin(p.x * 1.3 + u_time * 0.15));
  col += band * aur * (0.10 + 0.22 * f);

  // pointer glow
  vec2 m = (u_mouse - 0.5 * u_res) / u_res.y;
  col += vec3(0.25, 0.65, 0.9) * 0.05 * exp(-length(p - m) * 2.6);

  // vignette + grain
  col *= smoothstep(1.55, 0.25, length(p * vec2(0.75, 1.0)));
  col += (hash(gl_FragCoord.xy + fract(u_time) * 100.0) - 0.5) * 0.014;
  gl_FragColor = vec4(col, 1.0);
}
`;

/**
 * Hero: glowing "power lines": six transmission-line waves with current pulses travelling along
 * them, colored from the strain tint to sky blue. Faded on the left so the verdict text stays readable.
 * Output is premultiplied alpha so it composites over the card.
 */
export const POWERLINES_FRAG = `
precision highp float;
uniform vec2 u_res;
uniform float u_time;
uniform vec3 u_tint;
uniform float u_intensity;
void main() {
  vec2 uv = gl_FragCoord.xy / u_res;
  float aspect = u_res.x / u_res.y;
  float x = uv.x * aspect;
  vec3 col = vec3(0.0);
  for (int i = 0; i < 6; i++) {
    float fi = float(i);
    float y = 0.52
      + 0.16 * sin(x * (0.9 + fi * 0.22) + u_time * (0.30 + fi * 0.07) + fi * 1.7)
      + 0.05 * sin(x * 3.1 - u_time * (0.9 + fi * 0.1) + fi * 2.3)
      + (fi - 2.5) * 0.045;
    float d = abs(uv.y - y);
    float line = 0.0020 / (d + 0.0025);
    float pulse = pow(0.5 + 0.5 * sin(x * 5.0 - u_time * (1.6 + fi * 0.35) + fi * 2.1), 10.0);
    vec3 c = mix(u_tint, vec3(0.49, 0.83, 0.99), fi / 5.0);
    col += c * line * (0.22 + 1.1 * pulse);
  }
  float fade = mix(0.18, 1.0, smoothstep(0.10, 0.70, uv.x));
  fade *= smoothstep(0.0, 0.18, uv.y) * smoothstep(1.0, 0.82, uv.y);
  col *= fade * u_intensity;
  col = col / (1.0 + col);                 // soft tonemap
  float a = clamp(max(col.r, max(col.g, col.b)) * 1.4, 0.0, 1.0);
  gl_FragColor = vec4(col, a);
}
`;

/**
 * Ripple card: concentric rings expanding from a few "homes" on a slow-drifting caustic field.
 * u_amount (0..1, participation) adds sources, speeds the rings up and brightens them.
 */
export const RIPPLE_FRAG = `
precision highp float;
uniform vec2 u_res;
uniform float u_time;
uniform float u_amount;
void main() {
  vec2 uv = gl_FragCoord.xy / u_res;
  vec2 p = (gl_FragCoord.xy - 0.5 * u_res) / u_res.y;
  float amt = clamp(u_amount, 0.0, 1.0);
  float n = 2.0 + floor(amt * 4.0);             // 2..6 ripple sources
  float h = 0.0;
  for (int i = 0; i < 6; i++) {
    float fi = float(i);
    if (fi >= n) break;
    vec2 c = vec2(sin(fi * 2.4 + 0.3) * 0.85 * (u_res.x / u_res.y) * 0.5, 0.15 + 0.25 * cos(fi * 1.7));
    float d = length(p - c);
    float speed = 0.18 + 0.22 * amt;
    float ph = d * 26.0 - u_time * (2.0 + 2.5 * amt) * 1.0 - fi * 1.3;
    float ring = pow(0.5 + 0.5 * cos(ph), 14.0);
    float life = fract(u_time * speed + fi * 0.37);
    float radius = life * 1.4;
    ring *= smoothstep(radius, radius - 0.35, d) * (1.0 - life) * exp(-d * 1.2);
    h += ring;
  }
  vec3 cyan = vec3(0.49, 0.83, 0.99);
  vec3 teal = vec3(0.20, 0.83, 0.60);
  vec3 col = mix(teal, cyan, uv.x) * h * (0.35 + 0.65 * amt);
  col += vec3(0.02, 0.07, 0.10) * (1.0 - uv.y);  // faint water tint
  col = col / (1.0 + col);
  float a = clamp(max(col.r, max(col.g, col.b)) * 1.6, 0.0, 1.0);
  gl_FragColor = vec4(col, a);
}
`;
