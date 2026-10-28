import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { flushSync } from "react-dom";

export const FULLSCREEN_IDLE_MS = 1000;
export const SURFACE_TAP_SLOP = 5;
export function withinSurfaceTap(x: number, y: number, nextX: number, nextY: number) {
  return Math.hypot(nextX - x, nextY - y) <= SURFACE_TAP_SLOP;
}

/** Visibility only, in ordinary and wrapper fullscreen. Native VIDEO is platform-owned. */
export function useFullscreenControls({area, controls, fullscreen, canHide, canToggle, sourceKey}: {
  area: RefObject<HTMLDivElement | null>;
  controls: RefObject<HTMLDivElement | null>;
  fullscreen: boolean;
  canHide: boolean;
  canToggle: boolean;
  sourceKey: string;
}) {
  const [hidden, setHidden] = useState(false);
  const state = useRef({canHide, canToggle});
  state.current = {canHide, canToggle};
  const refresh = useRef<() => void>(() => {});

  useEffect(() => {
    const root = area.current, bar = controls.current;
    if (!root || !bar || (fullscreen && document.fullscreenElement !== root)) return;
    let timer = 0, alive = true, hovered = false, keyboard = false, keyboardFocus = false;
    let press: {id:number; x:number; y:number; tap:boolean; moved:boolean} | null = null;
    let touchUntil = 0;
    const inside = (target: EventTarget | null) => target instanceof Node && bar.contains(target);
    const neutral = (event: PointerEvent) => {
      const target = event.composedPath()[0];
      return target instanceof HTMLVideoElement || target === root.querySelector('.player-surface');
    };
    const compatibilityMouse = (event: PointerEvent) => event.pointerType === 'mouse' && performance.now() < touchUntil;
    const clear = () => window.clearTimeout(timer);
    const eligible = () => state.current.canHide && !press && !hovered && !keyboardFocus;
    function arm() {
      clear();
      if (eligible()) timer = window.setTimeout(() => {if (alive && eligible()) setHidden(true)}, FULLSCREEN_IDLE_MS);
    }
    function show() {setHidden(false); arm()}
    function move(event: PointerEvent) {
      if (compatibilityMouse(event)) return;
      if (press && event.pointerId === press.id) {
        if (!withinSurfaceTap(press.x, press.y, event.clientX, event.clientY)) press.moved = true;
        // A stationary touch must not undo the impending toggle; scrolling is not a tap.
        if (press.tap && !press.moved) return;
      }
      hovered = event.pointerType === 'mouse' && inside(event.target);
      if (event.pointerType === 'mouse' || press) show();
    }
    function down(event: PointerEvent) {
      if (compatibilityMouse(event)) return;
      if (event.pointerType !== 'mouse') touchUntil = performance.now() + 900;
      keyboard = false; keyboardFocus = false;
      hovered = event.pointerType === 'mouse' && inside(event.target);
      press = {id:event.pointerId, x:event.clientX, y:event.clientY,
        tap:!fullscreen && event.pointerType !== 'mouse' && event.isPrimary && event.button === 0 && neutral(event) && state.current.canToggle,
        moved:false};
      clear();
      if (!press.tap) show();
    }
    function up(event: PointerEvent) {
      if (compatibilityMouse(event) || !press || event.pointerId !== press.id) return;
      if (event.pointerType !== 'mouse') touchUntil = performance.now() + 900;
      const tap = press.tap && !press.moved && withinSurfaceTap(press.x, press.y, event.clientX, event.clientY) && neutral(event) && state.current.canToggle;
      press = null;
      hovered = event.pointerType === 'mouse' && inside(event.target);
      if (tap) {setHidden(value => !value); arm()}
      else show();
    }
    function cancel() {if (press) {press=null; show()}}
    function leave(event: PointerEvent) {
      if (event.pointerType !== 'mouse' || compatibilityMouse(event)) return;
      hovered = false; show();
    }
    function key() {
      keyboard = true; keyboardFocus = inside(document.activeElement);
      // Reveal/inert removal before Tab's native traversal, not one stop afterwards.
      flushSync(() => setHidden(false)); arm();
    }
    function focus(event: FocusEvent) {
      keyboardFocus = keyboard && inside(event.target);
      if (keyboard || inside(event.target)) show();
    }
    function blur(event: FocusEvent) {keyboardFocus = keyboard && inside(event.relatedTarget); arm()}
    function reset() {press = null; hovered = matchMedia('(hover: hover)').matches && bar!.matches(':hover'); keyboardFocus = keyboard && inside(document.activeElement); show()}
    root.addEventListener('pointermove', move, true);
    root.addEventListener('pointerdown', down, true);
    window.addEventListener('pointerup', up, true);
    window.addEventListener('pointercancel', cancel, true);
    root.addEventListener('pointerleave', leave);
    window.addEventListener('keydown', key, true);
    root.addEventListener('focusin', focus);
    root.addEventListener('focusout', blur);
    window.addEventListener('resize', reset);
    window.addEventListener('blur', reset);
    refresh.current = show; show();
    return () => {
      alive = false; clear(); refresh.current = () => {};
      root.removeEventListener('pointermove', move, true);
      root.removeEventListener('pointerdown', down, true);
      window.removeEventListener('pointerup', up, true);
      window.removeEventListener('pointercancel', cancel, true);
      root.removeEventListener('pointerleave', leave);
      window.removeEventListener('keydown', key, true);
      root.removeEventListener('focusin', focus);
      root.removeEventListener('focusout', blur);
      window.removeEventListener('resize', reset);
      window.removeEventListener('blur', reset);
    };
  }, [area, controls, fullscreen, sourceKey]);
  // Safety transitions reveal; time/progress rerenders do not undo a paused manual hide.
  useLayoutEffect(() => {refresh.current()}, [fullscreen, canHide, canToggle, sourceKey]);
  return hidden;
}
