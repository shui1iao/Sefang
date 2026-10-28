import {useLayoutEffect,useRef,useState,type RefObject} from 'react';
import {currentSession} from './auth-client';
import {resumeTime,type Resume} from './history-client';

export function atRestoreTarget(media:{seeking:boolean;readyState:number;currentTime:number},target:number){return !media.seeking&&media.readyState>=2&&Math.abs(media.currentTime-target)<.25}
/** Explicit history only. No delayed play: user activation remains a new click AFTER ready. */
export function useHistoryRestore(video:RefObject<HTMLVideoElement|null>,restore:Resume|undefined,group:string,part:{channel_id:number;message_id:number;stream:string;available:boolean}){
 const account=currentSession()?.id;
 const valid=!!restore&&restore.account_id===account&&restore.work_id===group&&restore.channel_id===part.channel_id&&restore.message_id===part.message_id&&part.available;
 const key=valid?`${account}/${group}/${part.stream}/${restore.id}/${restore.position}`:'';
 const [version,retry]=useState(0),[status,setStatus]=useState({key:'',version:0,phase:'ready'});
 const current=useRef(key);current.current=key;
 useLayoutEffect(()=>{
  const el=video.current;if(!key||!el||!restore)return;
  let alive=true,target:number|null=null,positioned=false,finished=false;
  const source=()=>!!el.currentSrc&&new URL(el.currentSrc,location.href).pathname===new URL(part.stream,location.href).pathname;
  const publish=(phase:string)=>{if(alive&&current.current===key)setStatus({key,version,phase})};
  const failed=()=>{finished=true;publish('failed')};
  const check=()=>{
   if(!alive||finished||!source())return;
   if(el.error){failed();return}
   if(el.readyState<1)return;
   if(!positioned){
    target=resumeTime(restore.position,el.duration);
    if(target===null){failed();return}
    positioned=true;el.pause();
    try{el.currentTime=target}catch{failed();return}
   }
   // loadedmetadata alone says nothing about the distant target being decoded.
   if(target!==null&&atRestoreTarget(el,target)){finished=true;publish('ready')}
  };
  publish('waiting');el.pause();
  const events=['loadedmetadata','durationchange','loadeddata','canplay','seeked','progress'] as const;
  events.forEach(event=>el.addEventListener(event,check));el.addEventListener('error',failed);check();
  return()=>{alive=false;events.forEach(event=>el.removeEventListener(event,check));el.removeEventListener('error',failed)};
 },[video,key,version,restore,part.stream]);
 const blocked=!!key&&(status.key!==key||status.version!==version||status.phase!=='ready');
 return {blocked,failed:blocked&&status.key===key&&status.phase==='failed',retry:()=>retry(x=>x+1)};
}
