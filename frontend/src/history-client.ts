import {currentSession,requireLogin,writeJson,type Session} from './auth-client';
export type Resume = {id:string;account_id:number;work_id:string;channel_id:number;message_id:number;position:number;note:string};
export type Sample = {channel_id:number;message_id:number;position:number;duration:number};
export type HistoryEvent = 'playing'|'progress'|'pause'|'seeked'|'ended'|'final';
export function resumeTime(value:number,duration:number){return Number.isFinite(value)&&value>=0&&Number.isFinite(duration)&&duration>0?Math.min(value,Math.max(0,duration-.1)):null}

export class HistoryWriteError extends Error {
 constructor(readonly status:number|'network'){super('历史记录未保存')}
 get retryable(){return this.status==='network'||(this.status>=500&&this.status<600)}
}
const backoff=[500,1500,4000];
/** Serialize writes within the original context. After an ambiguous failure,
 * replay its exact body before sending the latest eligible sample at a new sequence.
 * A 409 (delete/clear/old window) permanently stops this writer.
 */
export class HistoryRecorder {
 private context='';private sequence=0;private began=false;private sent=false;private busy=false;private disabled=false;
 private contextFailed=false;
 private queued:{sample:Sample;event:HistoryEvent}|null=null;
 private last=0;
 constructor(readonly account:Session,readonly work:string,context:Promise<{context:string;work_id:string}>,
  private send:(body:unknown)=>Promise<void>,private same:()=>boolean,private now=()=>Date.now(),private notify=()=>{}){
  const failed=()=>{this.contextFailed=true;this.queued=null;if(this.began&&this.same())this.notify()};
  context.then(data=>{if(!this.same()){this.stop();return}if(data.work_id!==work||!data.context){failed();return}this.context=data.context;this.drain()},failed);
 }
 record(sample:Sample,event:HistoryEvent){
  if(this.disabled||!this.current()||!Number.isFinite(sample.duration)||sample.duration<=0||!Number.isFinite(sample.position)||sample.position<0)return;
  if(event==='playing'&&!this.began){this.began=true;if(this.contextFailed)this.notify()}
  if(!this.began||this.contextFailed)return;
  const now=this.now();
  if(event==='progress'&&now-this.last<10000){
   // An already-eligible progress write can take a fresher position while waiting,
   // without adding a write or replacing a pending pause/seek/final event.
   if(this.queued?.event==='progress')this.queued={sample:{...sample},event};
   return;
  }
  this.last=now;this.queued={sample:{...sample},event};this.drain();
 }
 private stop(){this.disabled=true;this.queued=null}
 private current(){if(this.same())return true;this.stop();return false}
 private drain(){
  if(this.busy||!this.context||!this.queued||this.disabled||!this.current())return;
  const next=this.queued;this.queued=null;this.busy=true;
  const first=!this.sent;
  const body={...next.sample,context:this.context,sequence:++this.sequence,event:first?'playing':next.event};
  const send=async (attempt:number)=>{
   if(this.disabled||!this.current())return;
   try{await this.send(body)}catch(error){
    if(!this.current())return;
    if(error instanceof HistoryWriteError&&error.retryable&&attempt<backoff.length){setTimeout(()=>void send(attempt+1),backoff[attempt]);return}
    this.stop();if(error instanceof HistoryWriteError&&error.retryable)this.notify();return;
   }
   if(!this.current())return;
   this.busy=false;this.sent=true;
   if(first&&next.event!=='playing'&&!this.queued)this.queued=next;
   this.drain();
  };
  void send(0);
 }
}
export function historyRecorder(work:string,channel_id:number,message_id:number,notify?:()=>void){
 const account=currentSession();if(!account)return null;
 const same=()=>currentSession()?.id===account.id&&currentSession()?.csrf===account.csrf;
 const context=writeJson<{context:string;work_id:string}>('/api/history/context',{channel_id,message_id});
 return new HistoryRecorder(account,work,context,async body=>{
  const payload=JSON.stringify(body);
  let response:Response;
  try{response=await fetch('/api/history/progress',{method:'POST',keepalive:true,cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':account.csrf},body:payload})}catch{throw new HistoryWriteError('network')}
  if(response.status===401&&same())requireLogin();
  if(!response.ok)throw new HistoryWriteError(response.status);
 },same,undefined,notify);
}
