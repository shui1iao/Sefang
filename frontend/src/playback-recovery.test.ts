import {afterEach,describe,expect,it,vi} from 'vitest';
import {closePlayback,playbackLease} from './usePlayback';
import {playbackPosition,recoveryPoint,restorePosition} from './useHistoryRestore';

const deferred=<T>()=>{let resolve!:(value:T)=>void;const promise=new Promise<T>(done=>{resolve=done});return {promise,resolve}};
const old='/api/media/1/1?playback=old',fresh='/api/media/1/1?playback=new',replacement='/api/media/1/1?playback=replacement',next='/api/media/1/2?playback=new';
const origin='https://test';
class Media extends EventTarget {
 src=fresh;currentSrc=origin+old;readyState=0;seeking=false;duration=120;error:MediaError|null=null;paused=false;
 time=0;seeks:number[]=[];
 get currentTime(){return this.time}
 set currentTime(value:number){this.seeks.push(value);this.time=value;this.seeking=true}
 getAttribute(){return this.src}
 pause(){this.paused=true}
 emit(name:string){this.dispatchEvent(new Event(name))}
 native(){return this as unknown as HTMLMediaElement}
}
afterEach(()=>vi.unstubAllGlobals());

describe('explicit playback permit replacement',()=>{
 it('releases the valid old permit before publishing/acquiring a new one',async()=>{
  const manager=playbackLease(),steps:string[]=[],closing=deferred<void>();
  const close=async(id:string)=>{steps.push('close '+id);await closing.promise};
  const acquire=async(id:string)=>{steps.push('open '+id);return id};
  const open=(id:string)=>manager.open(()=>acquire(id),close,()=>true,id=>steps.push('src '+id),vi.fn());
  await open('old');const retry=open('new');await Promise.resolve();
  expect(steps).toEqual(['open old','src old','close old']);
  closing.resolve();await retry;
  expect(steps).toEqual(['open old','src old','close old','open new','src new']);
 });
 it('releases a late permit without installing it when replaced, or when leaving the work',async()=>{
  const manager=playbackLease(),pending=deferred<string>(),started=deferred<void>();
  const acquire=async()=>{started.resolve();return pending.promise},publish=vi.fn(),close=vi.fn(async()=>{}),fail=vi.fn();
  const first=manager.open(acquire,close,()=>true,publish,fail);await started.promise;
  const repeated=manager.open(async()=>'second',close,()=>true,publish,fail);
  pending.resolve('late');await first;await repeated;
  expect(publish.mock.calls).toEqual([['second']]);expect(close.mock.calls).toEqual([['late']]);
  const last=deferred<string>(),lastStarted=deferred<void>();
  const open=manager.open(async()=>{lastStarted.resolve();return last.promise},close,()=>true,publish,fail);await lastStarted.promise;
  const left=manager.cancel();last.resolve('after-leaving');await open;await left;
  expect(publish.mock.calls).toEqual([['second']]);expect(close.mock.calls).toEqual([['late'],['second'],['after-leaving']]);
 });
 it('requires an explicit retry after an ambiguous close or a failed open, without losing the old permit',async()=>{
  const manager=playbackLease(),close=vi.fn(async()=>{}),publish=vi.fn(),fail=vi.fn();
  const acquire=vi.fn(async()=>'old');
  const open=()=>manager.open(acquire,close,()=>true,publish,fail);
  await open();close.mockRejectedValueOnce(new TypeError('lost close receipt'));
  await open();expect(acquire).toHaveBeenCalledTimes(1);expect(fail).toHaveBeenCalledTimes(1);
  acquire.mockRejectedValueOnce(new Error('failed open'));
  await open();expect(close.mock.calls).toEqual([['old'],['old']]);expect(fail).toHaveBeenCalledTimes(2);
  acquire.mockResolvedValueOnce('new');await open();expect(publish.mock.calls).toEqual([['old'],['new']]);
 });
 it('can replace an expired playback permit without treating other 403s as successful releases',async()=>{
  const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({detail:'播放许可失效，请重新打开视频'}),{status:403}))
   .mockResolvedValueOnce(new Response(JSON.stringify({detail:'请求验证失败，请刷新重试'}),{status:403}));
  vi.stubGlobal('fetch',fetch);const manager=playbackLease(),acquire=vi.fn().mockResolvedValueOnce('old').mockResolvedValueOnce('new'),publish=vi.fn(),fail=vi.fn();
  const open=()=>manager.open(acquire,closePlayback,()=>true,publish,fail);
  await open();await open();await open();
  expect(publish.mock.calls).toEqual([['old'],['new']]);
  expect(fetch.mock.calls.map(([path])=>path)).toEqual(['/api/playbacks/old/close','/api/playbacks/new/close']);
  expect(fail.mock.calls[0][0]).toMatchObject({status:403,message:'请求验证失败，请刷新重试'});
 });
 it('does not publish a permit after its session changes while opening',async()=>{
  const manager=playbackLease(),pending=deferred<string>(),started=deferred<void>();let same=true;
  const publish=vi.fn(),close=vi.fn(async()=>{});
  const first=manager.open(async()=>{started.resolve();return pending.promise},close,()=>same,publish,vi.fn());
  await started.promise;same=false;pending.resolve('old-session');await first;
  expect(publish).not.toHaveBeenCalled();expect(close).not.toHaveBeenCalled();
 });
});

describe('retry positioning on the native element',()=>{
 it('ignores old-handle events and restores the exact attempt only after target data and seek completion',()=>{
  vi.stubGlobal('location',{href:origin+'/watch/1/1'});
  const media=new Media(),result=vi.fn();const stop=restorePosition(media.native(),fresh,53,result);
  media.readyState=4;media.emit('loadedmetadata');expect(media.seeks).toEqual([]);
  media.currentSrc=origin+fresh;media.readyState=1;media.emit('loadedmetadata');expect(media.seeks).toEqual([53]);
  media.readyState=4;media.emit('canplay');expect(result).not.toHaveBeenCalled();
  media.seeking=false;media.time=0;media.emit('seeked');expect(result).not.toHaveBeenCalled();
  media.time=53;media.paused=false;media.emit('seeked');expect(result.mock.calls).toEqual([['ready']]);expect(media.paused).toBe(true);
  stop();
 });
 it('does not sample an intermediate zero, an old handle, or a seek that has not landed',()=>{
  vi.stubGlobal('location',{href:origin+'/watch/1/1'});
  const media=new Media();media.readyState=4;media.time=49;media.src=old;
  expect(playbackPosition(media.native(),old,false)).toEqual({position:49,duration:120});
  media.src=fresh;media.time=0;
  expect(playbackPosition(media.native(),fresh,false)).toBeNull();
  media.currentSrc=origin+fresh;
  expect(playbackPosition(media.native(),fresh,true)).toBeNull();
  media.seeking=true;expect(playbackPosition(media.native(),fresh,false)).toBeNull();
  media.seeking=false;media.time=49;expect(playbackPosition(media.native(),fresh,false)?.position).toBe(49);
 });
 it('retries an unfinished history target paused, keeps a paused segment paused, and preserves playing intent if retry fails',()=>{
  const first=recoveryPoint(undefined,86,0,true);expect(first).toEqual({position:86,resume:false,history:true});
  expect(recoveryPoint(first,86,0,false)).toBe(first);
  expect(recoveryPoint(undefined,undefined,91,false)).toEqual({position:91,resume:false,history:false});
  const played=recoveryPoint(undefined,undefined,91,true);expect(played).toEqual({position:91,resume:true,history:false});
  expect(recoveryPoint(played,undefined,0,false)).toBe(played);
 });
 it('reports a current failure, does not publish from a cancelled segment, and can retry from the original target',()=>{
  vi.stubGlobal('location',{href:origin+'/watch/1/1'});
  const media=new Media(),failed=vi.fn(),stale=vi.fn(),result=vi.fn();
  media.currentSrc=origin+fresh;media.readyState=1;media.error={code:2} as MediaError;
  restorePosition(media.native(),fresh,78,failed)();expect(failed.mock.calls).toEqual([['failed']]);
  media.error=null;const stop=restorePosition(media.native(),fresh,78,stale);stop();
  media.src=next;media.currentSrc=origin+next;media.seeking=false;media.readyState=4;media.emit('seeked');
  media.src=replacement;media.currentSrc=origin+replacement;media.readyState=1;media.time=0;
  const retry=restorePosition(media.native(),replacement,78,result);
  media.readyState=4;media.seeking=false;media.emit('seeked');
  expect(stale).not.toHaveBeenCalled();expect(result.mock.calls).toEqual([['ready']]);expect(media.seeks).toEqual([78,78]);retry();
 });
});
