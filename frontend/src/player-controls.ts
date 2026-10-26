import {clampSeek} from './segments';

export const PLAYBACK_RATES=[0.5,0.75,1,1.25,1.5,1.75,2] as const;
export const MINUTE_JUMPS=[[-300,'5min','回退5分钟'],[-30,'30s','回退30秒'],[30,'30s','快进30秒'],[300,'5min','快进5分钟']] as const;

/** Manual seeks never manufacture an ended event or advance to another file. */
export function segmentSeek(current:number,requested:number,duration:number):{time:number;stop:boolean}|null{
 if(!Number.isFinite(current)||!Number.isFinite(requested)||!Number.isFinite(duration)||duration<=0)return null;
 const end=Math.max(0,duration-0.1);
 return {time:Math.min(end,clampSeek(current,requested-current,duration)),stop:requested<=0||requested>=end};
}
export function playerTime(seconds:number){
 if(!Number.isFinite(seconds)||seconds<0)return '--:--';
 const total=Math.floor(seconds),minutes=Math.floor(total/60),rest=String(total%60).padStart(2,'0');
 return total>=3600?`${Math.floor(total/3600)}:${String(minutes%60).padStart(2,'0')}:${rest}`:`${minutes}:${rest}`;
}
