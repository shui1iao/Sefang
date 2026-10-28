// A single must wait for the second click; never toggle and then "undo" a double.
export const SURFACE_CLICK_MS = 200;
export function surfaceClickQueue() {
 let timer: ReturnType<typeof setTimeout> | undefined;
 const cancel = () => { clearTimeout(timer); timer = undefined };
 return {cancel, single(action: () => void) { cancel(); timer = setTimeout(() => { timer = undefined; action() }, SURFACE_CLICK_MS) }};
}

/** Mouse-only neutral surface events. Existing buttons and shadow controls own their input. */
export function bindSurfaceGestures(root: HTMLDivElement | null, video: HTMLVideoElement | null, toggle: () => void, fullscreen: () => void) {
 if (!root || !video) return;
 const desktop = matchMedia('(min-width: 761px) and (hover: hover) and (pointer: fine)'), queue = surfaceClickQueue();
 const source = video.getAttribute('src');
 let firstNeutral = false;
 let alive = true, press: {id: number; x: number; y: number; moved: boolean; released: boolean} | null = null;
 const current = () => alive && desktop.matches && video.isConnected && video.getAttribute('src') === source;
 const neutral = (event: Event) => { const target = event.composedPath()[0]; return target === video || target === root };
 function cancel() { queue.cancel(); press = null; firstNeutral = false }
 function down(event: PointerEvent) {
  queue.cancel(); press = null;
  if (current() && neutral(event) && event.pointerType === 'mouse' && event.isPrimary && event.button === 0)
   press = {id: event.pointerId, x: event.clientX, y: event.clientY, moved: false, released: false};
  else firstNeutral = false;
 }
 function move(event: PointerEvent) {
  if (press && event.pointerId === press.id && Math.hypot(event.clientX - press.x, event.clientY - press.y) > 5) press.moved = true;
 }
 function up(event: PointerEvent) {
  if (!press || event.pointerId !== press.id) return;
  move(event); press.released = neutral(event) && event.button === 0;
 }
 const valid = (event: MouseEvent) => current() && neutral(event) && press?.released && !press.moved && event.button === 0 && event.detail > 0;
 function click(event: MouseEvent) {
  queue.cancel();
  const allowed = !!valid(event);
  if (event.detail === 1 || !allowed) firstNeutral = allowed;
  if (!allowed || event.detail !== 1) return;
  const wasPaused = video!.paused;
  queue.single(() => { if (current() && video!.paused === wasPaused) toggle() });
 }
 function double(event: MouseEvent) {
  queue.cancel();
  // Keep requestFullscreen in the trusted double-click task/user activation.
  if (firstNeutral && valid(event)) fullscreen();
  press = null; firstNeutral = false;
 }
 document.addEventListener('pointerdown', down, true);
 document.addEventListener('pointermove', move, true);
 document.addEventListener('pointerup', up, true);
 document.addEventListener('pointercancel', cancel, true);
 document.addEventListener('keydown', cancel, true);
 document.addEventListener('fullscreenchange', cancel);
 window.addEventListener('blur', cancel);
 desktop.addEventListener('change', cancel);
 video.addEventListener('emptied', cancel);
 root.addEventListener('click', click);
 root.addEventListener('dblclick', double);
 return () => {
  alive = false; cancel();
  document.removeEventListener('pointerdown', down, true);
  document.removeEventListener('pointermove', move, true);
  document.removeEventListener('pointerup', up, true);
  document.removeEventListener('pointercancel', cancel, true);
  document.removeEventListener('keydown', cancel, true);
  document.removeEventListener('fullscreenchange', cancel);
  window.removeEventListener('blur', cancel);
  desktop.removeEventListener('change', cancel);
  video.removeEventListener('emptied', cancel);
  root.removeEventListener('click', click);
  root.removeEventListener('dblclick', double);
 };
}
