import {currentSession,requireLogin,writeJson,type Session} from './auth-client';
export type Resume = {id:string;account_id:number;work_id:string;channel_id:number;message_id:number;position:number;note:string};
export type Sample = {channel_id:number;message_id:number;position:number;duration:number};
export type HistoryEvent = 'playing'|'progress'|'pause'|'seeked'|'ended'|'final';
export function resumeTime(value:number,duration:number){return Number.isFinite(value)&&value>=0&&Number.isFinite(duration)&&duration>0?Math.min(value,Math.max(0,duration-.1)):null}
/** An immutable sample always carries its original part, never a later DOM src.
 * Requests serialize/coalesce; only timeupdate is throttled. Delete 409 disables
 * this old context permanently; reopening is required to record again.
 */
export class HistoryRecorder {
 private context='';private sequence=0;private began=false;private sent=false;private busy=false;private disabled=false;
 private queued:{sample:Sample;event:HistoryEvent}|null=null;
 private last=0;
 constructor(readonly account:Session,readonly work:string,context:Promise<{context:string;work_id:string}>,
  private send:(body:unknown)=>Promise<void>,private same:()=>boolean,private now=()=>Date.now()){
  context.then(data=>{if(!this.same()||data.work_id!==work){this.disabled=true;return}this.context=data.context;this.drain()},()=>{this.disabled=true});
 }
 record(sample:Sample,event:HistoryEvent){
  if(this.disabled||!this.same()||!Number.isFinite(sample.duration)||sample.duration<=0||!Number.isFinite(sample.position)||sample.position<0)return;
  if(event==='playing')this.began=true;
  if(!this.began)return;
  if(event==='progress'&&this.now()-this.last<10000)return;
  this.last=this.now();this.queued={sample:{...sample},event};this.drain();
 }
 private drain(){
  if(this.busy||!this.context||!this.queued||this.disabled||!this.same())return;
  const next=this.queued;this.queued=null;this.busy=true;
  const first=!this.sent;
  const body={...next.sample,context:this.context,sequence:++this.sequence,event:first?'playing':next.event};
  this.send(body).then(()=>{this.sent=true;if(first&&next.event!=='playing'&&!this.queued)this.queued=next},()=>{this.disabled=true}).finally(()=>{this.busy=false;this.drain()});
 }
}
export function historyRecorder(work:string,channel_id:number,message_id:number){
 const account=currentSession();if(!account)return null;
 const same=()=>currentSession()?.id===account.id&&currentSession()?.csrf===account.csrf;
 const context=writeJson<{context:string;work_id:string}>('/api/history/context',{channel_id,message_id});
 return new HistoryRecorder(account,work,context,async body=>{
  if(!same())return;
  const response=await fetch('/api/history/progress',{method:'POST',keepalive:true,cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':account.csrf},body:JSON.stringify(body)});
  if(response.status===401)requireLogin();
  if(!response.ok)throw Error('历史记录未保存');
 },same);
}
