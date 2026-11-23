import {useCallback,useLayoutEffect,useRef,useState} from 'react';
import {currentSession,HttpWriteError,writeJson} from './auth-client';

/** Serialize release/open, including a handle received after its request was superseded. */
export function playbackLease(){
 let revision=0,chain=Promise.resolve();
 let held:{id:string;close:(id:string)=>Promise<void>;same:()=>boolean}|null=null;
 async function release(){
  if(!held)return;
  if(held.same())await held.close(held.id);
  held=null;
 }
 return {
  open(acquire:()=>Promise<string>,close:(id:string)=>Promise<void>,same:()=>boolean,publish:(id:string)=>void,fail:(error:unknown)=>void){
   const version=++revision;
   const live=()=>version===revision&&same();
   chain=chain.then(async()=>{
    if(!live())return;
    await release();
    if(!live())return;
    const id=await acquire();held={id,close,same};
    if(live())publish(id);else if(version===revision)await release();
    // Otherwise the queued renewal/cancel releases this handle before opening another.
   }).catch(error=>{if(live())fail(error)});
   return chain;
  },
  cancel(){revision++;chain=chain.then(release).catch(()=>{});return chain},
 };
}

export async function closePlayback(id:string){
 // A missing/expired handle is already gone. Retain it for the next explicit
 // retry if the close outcome is ambiguous (or was rejected for another reason).
 try{await writeJson(`/api/playbacks/${id}/close`,{})}catch(error){
  if(!(error instanceof HttpWriteError&&error.status===403&&error.message==='播放许可失效，请重新打开视频'))throw error;
 }
}

/** The account and window limits are still enforced by the original endpoints. */
export function usePlayback(group:string,channel:number,message:number){
 const [state,setState]=useState({scope:'',id:'',error:''});
 const manager=useRef<ReturnType<typeof playbackLease>|null>(null);
 const account=currentSession()?.id,csrf=currentSession()?.csrf;
 const scope=JSON.stringify([group,channel,message,account,csrf]);
 const renew=useCallback(()=>{
  setState({scope,id:'',error:''});
  manager.current??=playbackLease();
  void manager.current.open(
   async()=>(await writeJson<{id:string}>('/api/playbacks',{channel_id:channel,message_id:message})).id,
   closePlayback,
   ()=>currentSession()?.id===account&&currentSession()?.csrf===csrf,
   id=>setState({scope,id,error:''}),
   error=>setState({scope,id:'',error:error instanceof Error&&error.message||'请求未完成，请重试'}),
  );
 },[scope,channel,message,account,csrf]);
 useLayoutEffect(()=>{renew();return()=>{void manager.current?.cancel()}},[renew]);
 return {id:state.scope===scope?state.id:'',error:state.scope===scope?state.error:'',renew};
}
