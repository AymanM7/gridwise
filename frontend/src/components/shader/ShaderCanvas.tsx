"use client";

/**
 * Minimal WebGL1 fragment-shader canvas (no dependencies).
 *
 * - Full-quad vertex shader; you supply the fragment shader.
 * - Uniforms always provided: u_res (px), u_time (s), u_mouse (px, GL coords), plus `uniforms`.
 * - Renders at `scale` x devicePixelRatio (shaders are soft, so 0.5 is plenty and cheap).
 * - Pauses when off-screen or the tab is hidden; caps at `fps`.
 * - prefers-reduced-motion: draws a single still frame.
 * - No WebGL → renders nothing (the CSS background underneath still shows).
 */
import { useEffect, useRef } from "react";

const VERT = `
attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
`;

export type Uniforms = Record<string, number | [number, number] | [number, number, number]>;

export default function ShaderCanvas({
  frag,
  uniforms = {},
  scale = 0.5,
  fps = 40,
  className = "",
  trackMouse = false,
  stillTime = 6,
}: {
  frag: string;
  uniforms?: Uniforms;
  scale?: number;
  fps?: number;
  className?: string;
  trackMouse?: boolean;
  stillTime?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const uniRef = useRef<Uniforms>(uniforms);
  uniRef.current = uniforms;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl", { premultipliedAlpha: true, antialias: false, alpha: true });
    if (!gl || gl.isContextLost()) return;
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    const compile = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        console.warn("[ShaderCanvas]", gl.getShaderInfoLog(s));
        return null;
      }
      return s;
    };
    const vs = compile(gl.VERTEX_SHADER, VERT);
    const fs = compile(gl.FRAGMENT_SHADER, frag);
    if (!vs || !fs) return;
    const prog = gl.createProgram()!;
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(prog, "u_res");
    const uTime = gl.getUniformLocation(prog, "u_time");
    const uMouse = gl.getUniformLocation(prog, "u_mouse");
    const locs = new Map<string, WebGLUniformLocation | null>();
    const uloc = (n: string) => {
      if (!locs.has(n)) locs.set(n, gl.getUniformLocation(prog, n));
      return locs.get(n)!;
    };

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    let last = 0;
    let visible = true;
    const start = performance.now();
    const mouse = { x: -9999, y: -9999, tx: -9999, ty: -9999 };

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2) * scale;
      const w = Math.max(1, Math.round(canvas.clientWidth * dpr));
      const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);
      }
    };

    const draw = (tSec: number) => {
      resize();
      gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.uniform1f(uTime, tSec);
      // ease the mouse toward its target so the glow glides
      mouse.x += (mouse.tx - mouse.x) * 0.08;
      mouse.y += (mouse.ty - mouse.y) * 0.08;
      gl.uniform2f(uMouse, mouse.x, mouse.y);
      for (const [k, v] of Object.entries(uniRef.current)) {
        const l = uloc(k);
        if (!l) continue;
        if (typeof v === "number") gl.uniform1f(l, v);
        else if (v.length === 2) gl.uniform2f(l, v[0], v[1]);
        else gl.uniform3f(l, v[0], v[1], v[2]);
      }
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };

    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      if (!visible || document.hidden) return;
      if (now - last < 1000 / fps) return;
      last = now;
      draw((now - start) / 1000);
    };

    const onMove = (e: PointerEvent) => {
      const r = canvas.getBoundingClientRect();
      const k = canvas.width / Math.max(1, r.width);
      mouse.tx = (e.clientX - r.left) * k;
      mouse.ty = (r.bottom - e.clientY) * k; // GL y is up
      if (mouse.x < -1000) {
        mouse.x = mouse.tx;
        mouse.y = mouse.ty;
      }
    };

    const io = new IntersectionObserver(([e]) => (visible = e.isIntersecting), { threshold: 0 });
    io.observe(canvas);
    const ro = new ResizeObserver(() => reduce && draw(stillTime));
    ro.observe(canvas);
    if (trackMouse && !reduce) window.addEventListener("pointermove", onMove, { passive: true });

    if (reduce) draw(stillTime);
    else raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
      ro.disconnect();
      window.removeEventListener("pointermove", onMove);
      // Free GL objects but keep the context: React StrictMode re-runs this effect on the same
      // canvas, and getContext() would hand back a lost context if we called loseContext().
      gl.deleteBuffer(buf);
      gl.deleteProgram(prog);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
    };
  }, [frag, scale, fps, trackMouse, stillTime]);

  return <canvas ref={ref} aria-hidden className={`pointer-events-none block ${className}`} />;
}

/** "#f43f5e" → [0.957, 0.247, 0.369] */
export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.replace(/./g, "$&$&") : h, 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}
