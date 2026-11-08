"use client";

import ShaderCanvas, { hexToRgb } from "./ShaderCanvas";
import { AURORA_FRAG, POWERLINES_FRAG, RIPPLE_FRAG } from "./shaders";

/** Fixed full-viewport animated background. `tint` = strain color hex. */
export function AuroraBackground({ tint = "#7dd3fc" }: { tint?: string }) {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 bg-bg">
      <ShaderCanvas
        frag={AURORA_FRAG}
        uniforms={{ u_tint: hexToRgb(tint) }}
        scale={0.5}
        fps={30}
        trackMouse
        className="h-full w-full"
      />
      {/* keep the dot grid on top of the shader for texture */}
      <div className="page-dots absolute inset-0" />
    </div>
  );
}

/** Animated power lines for the hero card (absolute, fills its parent). */
export function PowerLines({ tint, intensity = 1 }: { tint: string; intensity?: number }) {
  return (
    <ShaderCanvas
      frag={POWERLINES_FRAG}
      uniforms={{ u_tint: hexToRgb(tint), u_intensity: intensity }}
      scale={0.75}
      fps={45}
      className="absolute inset-0 h-full w-full"
    />
  );
}

/** Expanding water-ripple rings for the Ripple card. `amount` 0..1 = participation. */
export function RippleField({ amount }: { amount: number }) {
  return (
    <ShaderCanvas
      frag={RIPPLE_FRAG}
      uniforms={{ u_amount: amount }}
      scale={0.6}
      fps={40}
      className="absolute inset-0 h-full w-full"
    />
  );
}
