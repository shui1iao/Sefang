import {describe,it,expect} from 'vitest';
import {keyAction} from './keyboard';
import {clampSeek,clampVolume,formatDuration,nextSegment,partIndex,segmentSummary,type Group} from './segments';

const part=(n:number,duration:number|null,available=true)=>({number:n,label_number:n,channel_id:1,message_id:10+n,duration,available,stream:`/api/videos/1/${10+n}/stream`,message_url:''});
const group:Group={id:'g1',status:'confirmed',part_count:3,index:0,total_duration:11292.947,duration_complete:true,parts:[part(1,3600),part(2,3600.5),part(3,4092.447)]};

describe('watch keyboard contract',()=>{
 it('maps each shortcut once and leaves editing/IME/modifiers alone',()=>{
  expect(keyAction({key:' '},'page')).toEqual({kind:'toggle'});expect(keyAction({key:'k',code:'KeyK'},'media')).toEqual({kind:'toggle'});
  expect(keyAction({key:'ArrowLeft'},'page')).toEqual({kind:'seek',delta:-5});expect(keyAction({key:'ArrowRight'},'media')).toEqual({kind:'seek',delta:5});
  expect(keyAction({key:'ArrowUp'},'page')).toEqual({kind:'volume',delta:0.05});expect(keyAction({key:'ArrowDown'},'page')).toEqual({kind:'volume',delta:-0.05});
  expect(keyAction({key:'M'},'page')).toEqual({kind:'mute'});expect(keyAction({key:'f'},'page')).toEqual({kind:'fullscreen'});
  expect(keyAction({key:'л',code:'KeyK'},'page')).toEqual({kind:'toggle'});
  for(const key of [' ','k','ArrowLeft','m','f'])expect(keyAction({key},'editable')).toBeNull();
  expect(keyAction({key:'k',isComposing:true},'page')).toBeNull();expect(keyAction({key:'Process',keyCode:229},'page')).toBeNull();
  for(const mod of ['ctrlKey','metaKey','altKey'])expect(keyAction({key:'f',[mod]:true},'page')).toBeNull();
  expect(keyAction({key:' ',defaultPrevented:true},'page')).toBeNull();expect(keyAction({key:'x'},'page')).toBeNull();
 });
 it('keeps native button/slider semantics and ignores long-press toggles',()=>{
  expect(keyAction({key:' '},'activatable')).toBeNull();expect(keyAction({key:'k'},'activatable')).toEqual({kind:'toggle'});
  expect(keyAction({key:'ArrowRight'},'slider')).toBeNull();expect(keyAction({key:' '},'slider')).toBeNull();
  for(const key of [' ','k','m','f'])expect(keyAction({key,repeat:true},'page')).toEqual({kind:'consume'});
  expect(keyAction({key:'ArrowRight',repeat:true},'page')).toEqual({kind:'seek',delta:5});
 });
});

describe('segment playback helpers',()=>{
 it('summarises current part and complete or partial totals',()=>{
  expect(segmentSummary(group,1)).toBe('第2/3段 · 本段1:00:01 · 全片合计3:08:13');
  expect(segmentSummary({...group,duration_complete:false,total_duration:7692.447},0)).toBe('第1/3段 · 本段1:00:00 · 已知合计2:08:12 · 部分段未取得');
  expect(formatDuration(59.6)).toBe('1:00');expect(formatDuration(null)).toBe('时长未知');
  expect(partIndex(group,'1','12')).toBe(1);expect(partIndex(group,'1','99')).toBe(-1);
 });
 it('continues only to an available next part and stops at the last',()=>{
  expect(nextSegment(group,0)).toEqual({next:1});expect(nextSegment(group,2)).toEqual({stop:'last'});
  expect(nextSegment({...group,parts:[part(1,1),part(2,1,false),part(3,1)]},0)).toEqual({stop:'unavailable'});
 });
 it('clamps seeking inside the current file and volume to 0..1',()=>{
  expect(clampSeek(2,-5,60)).toBe(0);expect(clampSeek(57,5,60)).toBeCloseTo(59.9);expect(clampSeek(59.95,5,60)).toBe(59.95);expect(clampSeek(10,5,60)).toBe(15);
  expect(clampVolume(0.98,0.05)).toBe(1);expect(clampVolume(0.02,-0.05)).toBe(0);expect(clampVolume(0.5,0.05)).toBe(0.55);
 });
});
