import {describe,it,expect} from 'vitest';
import {PLAYBACK_RATES,MINUTE_JUMPS,segmentSeek,playerTime} from './player-controls';
import {keyAction} from './keyboard';

describe('confirmed standalone player controls',()=>{
 it('has the selected rates, 5min/30s jump order and full direction labels',()=>{
  expect([...PLAYBACK_RATES]).toEqual([0.5,0.75,1,1.25,1.5,1.75,2]);
  expect([...MINUTE_JUMPS]).toEqual([[-300,'5min','回退5分钟'],[-30,'30s','回退30秒'],[30,'30s','快进30秒'],[300,'5min','快进5分钟']]);
 });
 it('keeps manual seeks in this file, pausing at each boundary',()=>{
  expect(segmentSeek(50,-550,1200)).toEqual({time:0,stop:true});
  expect(segmentSeek(1150,1750,1200)).toEqual({time:1199.9,stop:true});
  expect(segmentSeek(50,110,1200)).toEqual({time:110,stop:false});
  expect(segmentSeek(1199.95,1800,1200)).toEqual({time:1199.9,stop:true});
  expect(segmentSeek(0,0,0.05)).toEqual({time:0,stop:true});
 });
 it('applies exact 30s/300s deltas without crossing a segment boundary',()=>{
  for(const [delta] of MINUTE_JUMPS)expect(segmentSeek(600,600+delta,1200)).toEqual({time:600+delta,stop:false});
  expect(segmentSeek(20,20-30,1200)).toEqual({time:0,stop:true});
  expect(segmentSeek(1100,1100+300,1200)).toEqual({time:1199.9,stop:true});
 });
 it('rejects unknown metadata rather than guessing a seekable duration',()=>{
  for(const duration of [NaN,Infinity,0,-1])expect(segmentSeek(0,60,duration)).toBeNull();
  expect(segmentSeek(NaN,60,120)).toBeNull();expect(segmentSeek(0,Infinity,120)).toBeNull();
 });
 it('keeps menu keys and real range keyboard defaults out of global shortcuts',()=>{
  for(const key of [' ','ArrowLeft','ArrowRight','ArrowUp','ArrowDown','k','m','f'])expect(keyAction({key},'menu')).toBeNull();
  for(const key of [' ','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'])expect(keyAction({key},'slider')).toBeNull();
  expect(keyAction({key:' '},'activatable')).toBeNull();
 });
 it('uses playback time without rounding a near-ended file up to its end',()=>{
  expect(playerTime(59.9)).toBe('0:59');expect(playerTime(3601)).toBe('1:00:01');expect(playerTime(NaN)).toBe('--:--');
 });
});
