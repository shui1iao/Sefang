import {describe,it,expect} from 'vitest';
import {atRestoreTarget} from './useHistoryRestore';
import {historyTitle} from './History';
import type {Video} from './types';
import hook from './useHistoryRestore.ts?raw';
import player from './Player.tsx?raw';
const video=(v:object)=>v as Video;
describe('explicit resume readiness and presentation',()=>{
 it('metadata only cannot release a distant restore',()=>expect(atRestoreTarget({readyState:1,seeking:false,currentTime:45},45)).toBe(false));
 it('seeking is not ready even when an old decoded frame exists',()=>expect(atRestoreTarget({readyState:4,seeking:true,currentTime:45},45)).toBe(false));
 it('requires correct target, not merely loadeddata',()=>expect(atRestoreTarget({readyState:4,seeking:false,currentTime:0},45)).toBe(false));
 it('releases on readable target within finite timestamp tolerance',()=>expect(atRestoreTarget({readyState:2,seeking:false,currentTime:45.01},45)).toBe(true));
 it('has no delayed play or clock-driven readiness; cancels source listeners',()=>{
  expect(hook).not.toContain('.play(');expect(hook).not.toContain('setTimeout');expect(hook).toContain('alive=false;');expect(hook).toContain('removeEventListener');
  expect(player).toContain('if(restoring.current||!el');expect(player).toContain('data-history-restoring');
 });
 it('uses current DTO projection not persisted filename; number is not repeated',()=>expect(historyTitle(video({title:'OLD-FILENAME.mp4',code:'MIDA-022',display_title:'MIDA-022 · 作品标题'}))).toEqual({code:'MIDA-022',text:'作品标题'}));
 it('does not promote a filename in existing video.title without display_title',()=>expect(historyTitle(video({title:'MIDA-022(1).mp4',code:'MIDA-022'}))).toEqual({code:'MIDA-022',text:'作品标题暂未取得'}));
 it('rejects filename fallbacks in BOTH DTO candidates, preserving only reliable code',()=>{
  for(const ext of ['MP4','mkv','webm','mov','mpeg','3gp','m4v'])expect(historyTitle(video({title:'MIDA-022(1).'+ext,display_title:'MIDA-022(1).'+ext,code:'MIDA-022'}))).toEqual({code:'MIDA-022',text:'作品标题暂未取得'});
 });
 it('does not guess a code or turn extension removal into a title',()=>expect(historyTitle(video({title:'unknown_work.webm',code:''}))).toEqual({code:'',text:'作品标题暂未取得'}));
 it('keeps a real metadata title when the display candidate alone is filename-shaped',()=>expect(historyTitle(video({title:'原作品标题',display_title:'MIDA-022(1).mkv',code:'MIDA-022'}))).toEqual({code:'MIDA-022',text:'原作品标题'}));
 it('empty or code-only metadata has no invented work title',()=>{
  expect(historyTitle(video({title:'',display_title:'  ',code:''}))).toEqual({code:'',text:'作品标题暂未取得'});
  expect(historyTitle(video({title:'MIDA-022',code:'MIDA-022'}))).toEqual({code:'MIDA-022',text:'作品标题暂未取得'});
 });
 it('unavailable metadata is honest and never reveals the old filename',()=>expect(historyTitle(null)).toEqual({code:'',text:'作品资料当前不可用'}));
 it('does not guess an absent number or title translation',()=>expect(historyTitle(video({title:'原作品名',code:''}))).toEqual({code:'',text:'原作品名'}));
});
