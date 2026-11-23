import {useLayoutEffect,useState,type RefObject} from 'react';
import {currentSession} from './auth-client';
import {resumeTime,type Resume} from './history-client';

export function atRestoreTarget(media:{seeking:boolean;readyState:number;currentTime:number},target:number){return !media.seeking&&media.readyState>=2&&Math.abs(media.currentTime-target)<.25}
export function matchesPlaybackSource(el:HTMLMediaElement,src:string){return !!src&&el.getAttribute('src')===src&&el.currentSrc===new URL(src,location.href).href}
export function playbackPosition(el:HTMLMediaElement,src:string,blocked:boolean){
 if(blocked||el.error||!matchesPlaybackSource(el,src)||el.seeking||el.readyState<1)return null;
 const position=el.currentTime,duration=el.duration;
 return Number.isFinite(position)&&position>=0&&Number.isFinite(duration)&&duration>0?{position,duration}:null;
}
export type RecoveryPoint={position:number;resume:boolean;history:boolean};
export function recoveryPoint(unfinished:RecoveryPoint|undefined,historyPosition:number|undefined,lastPosition:number|undefined,wasPlaying:boolean):RecoveryPoint{
 if(unfinished)return unfinished;
 if(historyPosition!==undefined)return {position:historyPosition,resume:false,history:true};
 return {position:lastPosition??0,resume:wasPlaying,history:false};
}

/** Only respond to the expected handle and part on the existing native element. */
export function restorePosition(el:HTMLMediaElement,src:string,position:number,publish:(phase:'ready'|'failed')=>void){
 let alive=true,target:number|null=null,finished=false,seekIssued=false;
 const finish=(phase:'ready'|'failed')=>{if(finished)return;finished=true;publish(phase)};
 const check=(ev?:Event)=>{
  if(!alive||finished||!matchesPlaybackSource(el,src))return;
  if(el.error){finish('failed');return}
  if(el.readyState<1)return;
  if(target===null){
   target=resumeTime(position,el.duration);
   if(target===null){finish('failed');return}
   el.pause();
   try{if(el.currentTime!==target){el.currentTime=target;seekIssued=true}}catch{finish('failed');return}
  }
  // loadedmetadata alone says nothing about the distant target being decoded.
  if(atRestoreTarget(el,target)){el.pause();finish('ready');return}
  // Event-driven iOS Safari keyframe alignment guard: once seeked actually fires with
  // a decoded frame near the target (keyframe GOP <= 5s) or user-initiated playing starts,
  // release the restore mask without any clock-driven polling.
  if(ev?.type==='seeked'&&seekIssued&&!el.seeking&&el.readyState>=2&&Math.abs(el.currentTime-target)<=5){el.pause();finish('ready');return}
  if(ev?.type==='playing'&&!el.error&&el.readyState>=2){finish('ready')}
 };
 const events=['loadedmetadata','durationchange','loadeddata','canplay','canplaythrough','seeked','playing','progress','error'] as const;
 events.forEach(event=>el.addEventListener(event,check));check();
 return()=>{alive=false;events.forEach(event=>el.removeEventListener(event,check))};
}

/** History entry stays paused; explicit reload can use the same readiness gate. */
export function useHistoryRestore(video:RefObject<HTMLVideoElement|null>,restore:Resume|undefined,group:string,part:{channel_id:number;message_id:number;stream:string;available:boolean},src:string,retry?:{version:number;position:number}){
 const account=currentSession()?.id;
 const valid=!!restore&&restore.account_id===account&&restore.work_id===group&&restore.channel_id===part.channel_id&&restore.message_id===part.message_id&&part.available;
 const historyPosition=valid?restore.position:undefined;
 const target=retry?.position??historyPosition;
 const key=retry?`retry/${retry.version}`:valid?`history/${account}/${group}/${part.stream}/${restore.id}/${restore.position}`:'';
 const [status,setStatus]=useState({key:'',src:'',phase:'ready'});
 const blocked=!!key&&(status.key!==key||status.src!==src||status.phase!=='ready');
 useLayoutEffect(()=>{
  const el=video.current;if(!blocked||!src||!el||target===undefined)return;
  return restorePosition(el,src,target,phase=>setStatus({key,src,phase}));
 },[video,key,src,target,blocked]);
 return {blocked,historyPosition,failed:blocked&&status.key===key&&status.src===src&&status.phase==='failed'};
}
