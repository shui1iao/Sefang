export type Part={number:number;label_number:number|null;channel_id:number;message_id:number;duration:number|null;available:boolean;stream:string;message_url:string};
export type Group={id:string;status:string;part_count:number;index:number;total_duration:number|null;duration_complete:boolean;parts:Part[]};
export const SEEK_STEP=5,VOLUME_STEP=0.05;

export function formatDuration(seconds:number|null|undefined){
 if(typeof seconds!=='number'||!Number.isFinite(seconds)||seconds<0)return '时长未知';
 const total=Math.round(seconds);return total>=3600?`${Math.floor(total/3600)}:${String(Math.floor(total/60)%60).padStart(2,'0')}:${String(total%60).padStart(2,'0')}`:`${Math.floor(total/60)}:${String(total%60).padStart(2,'0')}`;
}
export function segmentSummary(group:Group,index:number){
 const part=group.parts[index];
 return `第${index+1}/${group.parts.length}段 · 本段${formatDuration(part?.duration)} · ${group.duration_complete?'全片合计':'已知合计'}${formatDuration(group.total_duration)}${group.duration_complete?'':' · 部分段未取得'}`;
}
export function partIndex(group:Group,cid:string,mid:string){return group.parts.findIndex(p=>String(p.channel_id)===cid&&String(p.message_id)===mid)}
/** 只有本段正常ended才调用：下一段存在且可用才续播；末段/不可用停在本段，不跳过。 */
export function nextSegment(group:Group,index:number):{next:number}|{stop:'last'|'unavailable'}{
 const next=index+1;if(next>=group.parts.length)return {stop:'last'};
 return group.parts[next].available?{next}:{stop:'unavailable'};
}
/** 键盘快进只在当前文件内移动，停在末尾前0.1秒，不借seek到结尾触发跨段。 */
export function clampSeek(current:number,delta:number,duration:number){
 const value=Math.max(0,current+delta);if(!Number.isFinite(duration)||duration<=0)return value;
 const end=Math.max(0,duration-0.1);if(delta>0&&current>=end)return current;return Math.min(end,value);
}
export function clampVolume(volume:number,delta:number){return Math.min(1,Math.max(0,Math.round((volume+delta)*100)/100))}
