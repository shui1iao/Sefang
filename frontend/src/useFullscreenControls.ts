import { useLayoutEffect, useRef, useState, type RefObject } from "react";
import { flushSync } from "react-dom";

export const FULLSCREEN_IDLE_MS = 1000;

/** Visibility only: never handles playback, source, gestures or seek actions. */
export function useFullscreenControls({
  area,
  controls,
  fullscreen,
  canHide,
}: {
  area: RefObject<HTMLDivElement | null>;
  controls: RefObject<HTMLDivElement | null>;
  fullscreen: boolean;
  canHide: boolean;
}) {
  const [hidden, setHidden] = useState(false);
  const enabled = useRef(false);
  enabled.current = fullscreen && canHide;
  const refresh = useRef<() => void>(() => {});

  useLayoutEffect(() => {
    const root = area.current,
      bar = controls.current;
    // A system/native VIDEO fullscreen has its own controls; only own our wrapper.
    if (!fullscreen || !root || !bar || document.fullscreenElement !== root)
      return;
    let timer = 0,
      alive = true,
      pressed = false,
      hovered = false;
    let keyboard = false,
      keyboardFocus = false;
    const inside = (target: EventTarget | null) =>
      target instanceof Node && bar.contains(target);
    const clear = () => window.clearTimeout(timer);
    const eligible = () =>
      enabled.current && !pressed && !hovered && !keyboardFocus;
    function arm() {
      clear();
      if (eligible())
        timer = window.setTimeout(() => {
          if (alive && eligible()) setHidden(true);
        }, FULLSCREEN_IDLE_MS);
    }
    function show() {
      setHidden(false);
      arm();
    }
    function move(event: PointerEvent) {
      hovered = event.pointerType === "mouse" && inside(event.target);
      show();
    }
    function down(event: PointerEvent) {
      pressed = true;
      keyboard = false;
      keyboardFocus = false;
      hovered = event.pointerType === "mouse" && inside(event.target);
      show();
    }
    function up(event: PointerEvent) {
      pressed = false;
      hovered = event.pointerType === "mouse" && inside(event.target);
      show();
    }
    function leave() {
      hovered = false;
      show();
    }
    function key() {
      keyboard = true;
      keyboardFocus = inside(document.activeElement);
      // Reveal before Tab's native focus traversal, not one tab stop afterwards.
      flushSync(() => setHidden(false));
      arm();
    }
    function focus(event: FocusEvent) {
      keyboardFocus = keyboard && inside(event.target);
      show();
    }
    function blur(event: FocusEvent) {
      keyboardFocus = keyboard && inside(event.relatedTarget);
      // Hiding an inert mouse-focused bar may blur it; do not immediately reveal it.
      arm();
    }
    root.addEventListener("pointermove", move, true);
    root.addEventListener("pointerdown", down, true);
    window.addEventListener("pointerup", up, true);
    window.addEventListener("pointercancel", up, true);
    root.addEventListener("pointerleave", leave);
    window.addEventListener("keydown", key, true);
    root.addEventListener("focusin", focus);
    root.addEventListener("focusout", blur);
    refresh.current = show;
    show();
    return () => {
      alive = false;
      clear();
      refresh.current = () => {};
      root.removeEventListener("pointermove", move, true);
      root.removeEventListener("pointerdown", down, true);
      window.removeEventListener("pointerup", up, true);
      window.removeEventListener("pointercancel", up, true);
      root.removeEventListener("pointerleave", leave);
      window.removeEventListener("keydown", key, true);
      root.removeEventListener("focusin", focus);
      root.removeEventListener("focusout", blur);
    };
  }, [area, controls, fullscreen]);

  useLayoutEffect(() => {
    refresh.current();
  }, [fullscreen, canHide]);
  return enabled.current && hidden;
}
