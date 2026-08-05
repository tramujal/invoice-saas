"use client";

import { useEffect, useRef, useState } from "react";

const DEFAULT_DURATION_MS = 500;

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/** Animates a numeric KPI from its previous value to `target` over a short
 * duration -- the Financial Dashboard's own "animated counters" requirement
 * (no existing primitive for this anywhere else in the app). `null`/`NaN`
 * targets pass through unanimated (there's nothing to count toward), and a
 * value that hasn't visually changed skips the animation entirely rather
 * than re-running it on every unrelated re-render. requestAnimationFrame-
 * driven, cancelled on unmount or if `target` changes mid-flight. */
export function useAnimatedNumber(target: number | null, durationMs: number = DEFAULT_DURATION_MS): number | null {
  const [displayed, setDisplayed] = useState<number | null>(target);
  const frameRef = useRef<number | null>(null);
  const fromRef = useRef<number | null>(target);

  useEffect(() => {
    if (target === null || Number.isNaN(target)) {
      setDisplayed(target);
      fromRef.current = target;
      return;
    }
    const from = fromRef.current ?? target;
    if (from === target) {
      setDisplayed(target);
      return;
    }

    const start = performance.now();
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);

    function tick(now: number) {
      const elapsed = now - start;
      const progress = Math.min(1, elapsed / durationMs);
      const eased = easeOutCubic(progress);
      setDisplayed(from + (target! - from) * eased);
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = target;
      }
    }
    frameRef.current = requestAnimationFrame(tick);

    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, durationMs]);

  return displayed;
}
