import {afterEach,describe,expect,it,vi} from 'vitest';
import {SURFACE_CLICK_MS,surfaceClickQueue} from './surface-gestures';
afterEach(()=>vi.useRealTimers());
describe('surface single/double arbitration',()=>{
 it('defers one single exactly once, not an immediate play/pause flash',()=>{vi.useFakeTimers();const q=surfaceClickQueue(),action=vi.fn();q.single(action);vi.advanceTimersByTime(SURFACE_CLICK_MS-1);expect(action).not.toHaveBeenCalled();vi.advanceTimersByTime(1);expect(action).toHaveBeenCalledTimes(1);vi.advanceTimersByTime(1000);expect(action).toHaveBeenCalledTimes(1)});
 it('cancels for a second pointerdown before either double click action',()=>{vi.useFakeTimers();const q=surfaceClickQueue(),action=vi.fn();for(const delay of [70,150]){q.single(action);vi.advanceTimersByTime(delay);q.cancel();vi.advanceTimersByTime(1000)}expect(action).not.toHaveBeenCalled()});
 it('accepts a single before a slow 420ms double; no restoration',()=>{vi.useFakeTimers();expect(SURFACE_CLICK_MS).toBe(200);const q=surfaceClickQueue(),action=vi.fn();q.single(action);vi.advanceTimersByTime(420);expect(action).toHaveBeenCalledTimes(1);q.cancel();vi.advanceTimersByTime(1000);expect(action).toHaveBeenCalledTimes(1)});
 it('cleanup cancels a pending source/segment/unmount action',()=>{vi.useFakeTimers();const old=surfaceClickQueue(),next=surfaceClickQueue(),a=vi.fn(),b=vi.fn();old.single(a);old.cancel();next.single(b);vi.advanceTimersByTime(SURFACE_CLICK_MS);expect(a).not.toHaveBeenCalled();expect(b).toHaveBeenCalledTimes(1)});
});
