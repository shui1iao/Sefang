import {afterEach,describe,it,expect,vi} from 'vitest';
import {HistoryRecorder,HistoryWriteError,historyRecorder,resumeTime} from './history-client';
import {setSession,type Session} from './auth-client';
const me={id:1,csrf:'scope'} as Session;
const sample={channel_id:123,message_id:1,position:5,duration:120};
const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve()};
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();setSession(null)});
describe('history recorder',()=>{
 it('does not record details, metadata, preload, pause or seek before real playing',async()=>{const calls:unknown[]=[];const r=new HistoryRecorder(me,'g',Promise.resolve({context:'k',work_id:'g'}),async b=>{calls.push(b)},()=>true);for(const event of ['progress','pause','seeked','final','ended'] as const)r.record(sample,event);await tick();expect(calls).toEqual([]);r.record(sample,'playing');await tick();expect(calls).toHaveLength(1)});
 it('throttles timeupdates to ten seconds but flushes pause/seek/background/part final',async()=>{const calls:unknown[]=[];let now=10000;const r=new HistoryRecorder(me,'g',Promise.resolve({context:'k',work_id:'g'}),async b=>{calls.push(b)},()=>true,()=>now);r.record(sample,'playing');await tick();now+=9000;r.record(sample,'progress');await tick();expect(calls).toHaveLength(1);now+=1000;r.record({...sample,position:15},'progress');await tick();expect(calls).toHaveLength(2);for(const event of ['pause','seeked','ended','final'] as const){r.record(sample,event);await tick()}expect(calls).toHaveLength(6)});
 it('immutable old-part flush never takes new-part keys; late sequences remain ordered',async()=>{const calls:unknown[]=[];const r=new HistoryRecorder(me,'g',Promise.resolve({context:'k',work_id:'g'}),async b=>{calls.push(b)},()=>true);r.record(sample,'playing');await tick();r.record({...sample,position:19},'final');await tick();r.record({...sample,message_id:2,position:0},'playing');await tick();expect(calls).toMatchObject([{message_id:1,sequence:1},{message_id:1,position:19,sequence:2},{message_id:2,position:0,sequence:3}])});
 it('ignores late context for another group and account change/logout',async()=>{const calls:unknown[]=[];let same=true;let resolve!:(v:{context:string;work_id:string})=>void;const p=new Promise<{context:string;work_id:string}>(r=>resolve=r);const r=new HistoryRecorder(me,'g',p,async b=>{calls.push(b)},()=>same);r.record(sample,'playing');same=false;resolve({context:'k',work_id:'g'});await tick();expect(calls).toEqual([]);const q=new HistoryRecorder(me,'g',Promise.resolve({context:'k',work_id:'other'}),async b=>{calls.push(b)},()=>true);q.record(sample,'playing');await tick();expect(calls).toEqual([])});
 it('a 409 permanently stops the old writer, even after a retried 5xx',async()=>{
  vi.useFakeTimers();let calls=0;
  const r=new HistoryRecorder(me,'g',Promise.resolve({context:'k',work_id:'g'}),async()=>{calls++;throw new HistoryWriteError(calls===1?503:409)},()=>true);
  r.record(sample,'playing');await tick();r.record({...sample,position:9},'pause');
  await vi.advanceTimersByTimeAsync(500);r.record(sample,'final');r.record(sample,'playing');
  await vi.runAllTimersAsync();expect(calls).toBe(2);
 });
 it('replays the exact initial payload when the server committed but the receipt was lost, then sends the latest sample and event at a fresh sequence',async()=>{
  vi.useFakeTimers();setSession(me);
  const sent:string[]=[];let committed=0;const applied:unknown[]=[];
  const fetch=vi.fn(async(path:string,init:RequestInit)=>{
   if(path==='/api/history/context')return new Response(JSON.stringify({context:'original',work_id:'g'}));
   expect(path).toBe('/api/history/progress');expect((init.headers as Record<string,string>)['X-CSRF-Token']).toBe(me.csrf);
   const payload=String(init.body);sent.push(payload);const body=JSON.parse(payload);
   if(body.sequence<=committed)return new Response('{"ok":true,"stale":true}');
   committed=body.sequence;applied.push(body);
   if(committed===1)throw new TypeError('response lost');
   return new Response('{"ok":true}');
  });
  vi.stubGlobal('fetch',fetch);const notice=vi.fn(),r=historyRecorder('g',123,1,notice)!;
  r.record(sample,'playing');await tick();expect(sent).toHaveLength(1);
  r.record({...sample,position:18},'final');r.record({...sample,message_id:2,position:1},'playing');
  r.record({...sample,message_id:2,position:21},'seeked');
  await vi.advanceTimersByTimeAsync(499);expect(sent).toHaveLength(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(sent).toHaveLength(3);expect(sent[0]).toBe(sent[1]);
  expect(applied).toMatchObject([
   {context:'original',sequence:1,event:'playing',message_id:1,position:5},
   {context:'original',sequence:2,event:'seeked',message_id:2,position:21},
  ]);expect(fetch.mock.calls.filter(([path])=>path==='/api/history/context')).toHaveLength(1);expect(notice).not.toHaveBeenCalled();
 });
 it('coalesces the latest progress into an already queued write without bypassing its ten-second throttle',async()=>{
  vi.useFakeTimers();const calls:unknown[]=[];let now=10000,fail!:()=>void;
  const first=new Promise<void>((_,reject)=>{fail=()=>reject(new HistoryWriteError(502))});
  const r=new HistoryRecorder(me,'g',Promise.resolve({context:'k',work_id:'g'}),async body=>{calls.push(body);if(calls.length===1)await first},()=>true,()=>now);
  r.record(sample,'playing');await tick();
  now=20000;r.record({...sample,position:15},'progress');fail();await tick();
  now=20100;r.record({...sample,position:16},'progress');await vi.advanceTimersByTimeAsync(500);
  expect(calls).toMatchObject([{sequence:1,position:5},{sequence:1,position:5},{sequence:2,event:'progress',position:16}]);
  now=29999;r.record({...sample,position:24},'progress');await tick();expect(calls).toHaveLength(3);
 });
 it.each([{...me,id:2},{...me,csrf:'new-session'},null])('drops the pending retry when the account/session changes (%j)',async account=>{
  vi.useFakeTimers();setSession(me);
  const fetch=vi.fn(async(path:string)=>path==='/api/history/context'?new Response(JSON.stringify({context:'original',work_id:'g'})):new Response('',{status:502}));
  vi.stubGlobal('fetch',fetch);const notice=vi.fn(),r=historyRecorder('g',123,1,notice)!;
  r.record(sample,'playing');await tick();expect(fetch).toHaveBeenCalledTimes(2);
  setSession(account);await vi.runAllTimersAsync();r.record({...sample,position:22},'final');
  expect(fetch).toHaveBeenCalledTimes(2);expect(notice).not.toHaveBeenCalled();
 });
 it('never reacquires an ambiguously issued context; only actual playback warrants a notice',async()=>{
  vi.useFakeTimers();setSession(me);
  const fetch=vi.fn(async(path:string)=>{expect(path).toBe('/api/history/context');throw new TypeError('context response lost')});vi.stubGlobal('fetch',fetch);
  const notice=vi.fn(),r=historyRecorder('g',123,1,notice)!;await tick();expect(notice).not.toHaveBeenCalled();
  r.record(sample,'playing');r.record(sample,'final');await vi.runAllTimersAsync();
  expect(fetch).toHaveBeenCalledTimes(1);expect(fetch.mock.calls[0]?.[0]).toBe('/api/history/context');expect(notice).toHaveBeenCalledOnce();
 });
 it('bounds retryable failures, never retries a non-retryable response',async()=>{
  vi.useFakeTimers();const ctx={context:'k',work_id:'g'},notice=vi.fn();
  const send=vi.fn(async()=>{throw new HistoryWriteError(503)});
  const r=new HistoryRecorder(me,'g',Promise.resolve(ctx),send,()=>true,undefined,notice);
  r.record(sample,'playing');await tick();
  for(const [delay,attempts] of [[500,2],[1500,3],[4000,4]]){
   await vi.advanceTimersByTimeAsync(delay-1);expect(send).toHaveBeenCalledTimes(attempts-1);
   await vi.advanceTimersByTimeAsync(1);expect(send).toHaveBeenCalledTimes(attempts);
  }
  r.record(sample,'final');await vi.runAllTimersAsync();expect(send).toHaveBeenCalledTimes(4);expect(notice).toHaveBeenCalledOnce();
  const invalid=vi.fn(async()=>{throw new HistoryWriteError(429)});
  const q=new HistoryRecorder(me,'g',Promise.resolve(ctx),invalid,()=>true);
  q.record(sample,'playing');await vi.runAllTimersAsync();expect(invalid).toHaveBeenCalledOnce();
 });
 it('pending context coalesces final sample without mistaking it for unopened playback',async()=>{const calls:unknown[]=[];let done!:(v:{context:string;work_id:string})=>void;const p=new Promise<{context:string;work_id:string}>(r=>done=r);const r=new HistoryRecorder(me,'g',p,async b=>{calls.push(b)},()=>true);r.record(sample,'playing');r.record({...sample,position:18},'final');done({context:'k',work_id:'g'});await tick();expect(calls).toMatchObject([{event:'playing',position:18},{event:'final',position:18}])});
 it('resume clamp cannot seek past duration or accept invalid time; no play action',()=>{expect(resumeTime(150,120)).toBe(119.9);expect(resumeTime(NaN,120)).toBe(null);expect(resumeTime(-1,120)).toBe(null);expect(resumeTime(40,120)).toBe(40)});
});
