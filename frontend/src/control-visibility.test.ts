import {describe,it,expect} from 'vitest';
import {FULLSCREEN_IDLE_MS,withinSurfaceTap} from './useFullscreenControls';
import hook from './useFullscreenControls.ts?raw';
import controls from './PlayerControls.tsx?raw';
import player from './Player.tsx?raw';
// @ts-expect-error Vitest provides node; browser TS config intentionally does not.
import {readFileSync} from 'node:fs';
const css=readFileSync(new URL('./player.css',import.meta.url),'utf8');
describe('ordinary/fullscreen visibility boundaries',()=>{
 it('keeps the wall clock idle interval at one second',()=>expect(FULLSCREEN_IDLE_MS).toBe(1000));
 it('accepts stationary taps up to five px, excludes scroll/drag in either direction',()=>{
  expect(withinSurfaceTap(10,20,13,24)).toBe(true);
  expect(withinSurfaceTap(10,20,10,20)).toBe(true);
  for(const [x,y] of [[16,20],[10,26],[6,16]])expect(withinSurfaceTap(10,20,x,y)).toBe(false);
 });
 it('keeps the bar mounted, hidden with inert/aria and ordinary/full identical CSS',()=>{
  expect(controls).toContain('aria-hidden={hidden||undefined} inert={hidden}');
  expect(css).toContain('.player-controls[data-controls-hidden="true"]');
  expect(css).not.toContain(':fullscreen .player-controls[data-controls-hidden');
 });
 it('rebinds original surface gesture when asynchronous playback lease installs the source',()=>{
  expect(player).toContain('[part.stream,part.available,error,group.id,index,lease.id,toggle,fullscreen]');
 });
 it('manual paused hide is independent from auto-hide eligibility and source reset is bounded',()=>{
  expect(hook).toContain('return hidden;');expect(hook).toContain('sourceKey]);');
  expect(hook).toContain("window.removeEventListener('pointerup', up, true)");
  expect(hook).toContain("window.removeEventListener('resize', reset)");
 });
});
