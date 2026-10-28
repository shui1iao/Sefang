import {createElement,useEffect,useLayoutEffect,useRef,useState,type RefObject} from 'react';
import * as Menu from '@radix-ui/react-dropdown-menu';
// A standalone UI element only: importing the controller/React barrel creates probe media.
import 'media-chrome/media-time-range.js';
import {PLAYBACK_RATES,MINUTE_JUMPS,playerTime} from './player-controls';
import {useFullscreenControls} from './useFullscreenControls';

export type PlaybackState={time:number;duration:number;ready:boolean;paused:boolean;ended:boolean;loading:boolean;volume:number;muted:boolean;buffered:number[][]};
export const emptyPlayback:PlaybackState={time:0,duration:NaN,ready:false,paused:true,ended:false,loading:false,volume:1,muted:false,buffered:[]};
type TimelineElement=HTMLElement&{mediaCurrentTime:number;mediaDuration:number;mediaSeekable:number[]|undefined;mediaBuffered:number[][];mediaPaused:boolean;mediaEnded:boolean;mediaLoading:boolean;mediaPlaybackRate:number};
function Timeline({state,rate,onSeek}:{state:PlaybackState;rate:number;onSeek:(seconds:number)=>void}){
 const ref=useRef<TimelineElement|null>(null),action=useRef(onSeek);action.current=onSeek;
 useEffect(()=>{const el=ref.current;if(!el)return;const seek=(event:Event)=>action.current(Number((event as CustomEvent<number>).detail));el.addEventListener('mediaseekrequest',seek);return()=>el.removeEventListener('mediaseekrequest',seek)},[]);
 useLayoutEffect(()=>{const el=ref.current;if(!el)return;Object.assign(el,{mediaCurrentTime:state.time,mediaDuration:state.duration,mediaSeekable:state.ready?[0,state.duration]:undefined,mediaBuffered:state.buffered,mediaPaused:state.paused,mediaEnded:state.ended,mediaLoading:state.loading,mediaPlaybackRate:rate});el.toggleAttribute('disabled',!state.ready);if(state.ready)el.removeAttribute('aria-disabled');else el.setAttribute('aria-disabled','true')},[state,rate]);
 return createElement('media-time-range',{ref,className:'player-timeline','aria-label':'播放进度','data-player-timeline':''});
}
function Icon({name}:{name:'play'|'pause'|'muted'|'volume'|'settings'|'fullscreen'|'rewind'|'forward'}){
 const paths={rewind:<path d="m11 5-8 7 8 7Zm10 0-8 7 8 7Z"/>,forward:<path d="m3 5 8 7-8 7Zm10 0 8 7-8 7Z"/>,play:<path d="m8 5 11 7-11 7Z"/>,pause:<><path d="M8 5v14M16 5v14"/></>,muted:<><path d="M11 5 6 9H3v6h3l5 4Z"/><path d="m16 9 6 6m0-6-6 6"/></>,volume:<><path d="M11 5 6 9H3v6h3l5 4Z"/><path d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/></>,settings:<><path d="m9 3-.7 2.2-2 .9L4.2 6l-1.5 2.6L4.2 10v2L2.7 14l1.5 2.6 2.1-.1 2 .9L9 20h3l.7-2.6 2-.9 2.1.1 1.5-2.6-1.5-2v-2l1.5-1.4L16.8 6l-2.1.1-2-.9L12 3Z"/><circle cx="10.5" cy="11.5" r="3"/></>,fullscreen:<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>};
 return <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}
export function PlayerControls({state,rate,available,fullscreen,sourceKey,area,onToggle,onSeek,onVolume,onMute,onRate,onFullscreen,onMenuOpen}:{state:PlaybackState;rate:number;available:boolean;fullscreen:boolean;sourceKey:string;area:RefObject<HTMLDivElement|null>;onToggle:()=>void;onSeek:(seconds:number)=>void;onVolume:(volume:number)=>void;onMute:()=>void;onRate:(rate:number)=>void;onFullscreen:()=>void;onMenuOpen:(open:boolean)=>void}){
 const [open,setOpen]=useState(false);
 const controls=useRef<HTMLDivElement>(null);
 const hidden=useFullscreenControls({area,controls,fullscreen,sourceKey,canToggle:available&&state.ready&&!state.ended&&!state.loading&&!open,canHide:available&&state.ready&&!state.paused&&!state.ended&&!state.loading&&!open});
 function menu(next:boolean){setOpen(next);onMenuOpen(next)}
 useEffect(()=>()=>onMenuOpen(false),[onMenuOpen]);
 return <div ref={controls} className="player-controls" data-player-controls="" data-controls-hidden={hidden?'true':undefined} aria-hidden={hidden||undefined} inert={hidden}>
   <div className="player-toolbar" role="group" aria-label="播放控制">
    <button type="button" className="player-control" aria-label={state.paused?'播放':'暂停'} title={state.paused?'播放 (Space / K)':'暂停 (Space / K)'} disabled={!available} onClick={onToggle}><Icon name={state.paused?'play':'pause'}/></button>
    <span className="player-time" data-player-time="">{playerTime(state.time)} <span>/</span> {playerTime(state.duration)}</span>
    <Timeline state={{...state,ready:available&&state.ready}} rate={rate} onSeek={onSeek}/>
    <div className="player-volume">
     <button type="button" className="player-control" aria-label={state.muted?'取消静音':'静音'} title={state.muted?'取消静音 (M)':'静音 (M)'} aria-pressed={state.muted} onClick={onMute}><Icon name={state.muted||state.volume===0?'muted':'volume'}/></button>
     <input type="range" aria-label="音量" min="0" max="1" step="0.05" value={state.muted?0:state.volume} onChange={event=>onVolume(Number(event.target.value))}/>
    </div>
    <Menu.Root open={open} onOpenChange={menu} modal={false}>
     <Menu.Trigger asChild><button type="button" className="player-control player-settings-trigger" aria-label="播放倍速" title="播放倍速"><span>{rate}×</span></button></Menu.Trigger>
     <Menu.Portal container={fullscreen?area.current:undefined}><Menu.Content className="picker-layer picker-menu player-settings-menu" data-player-settings="" side={fullscreen?'top':'bottom'} align="end" sideOffset={8} collisionPadding={8} avoidCollisions loop>
      <Menu.Label className="picker-menu-label">播放速度</Menu.Label><Menu.RadioGroup value={String(rate)} onValueChange={value=>{onRate(Number(value));menu(false)}} aria-label="播放速度">{PLAYBACK_RATES.map(value=><Menu.RadioItem className="picker-option" key={value} value={String(value)} data-player-rate={value}><span className="picker-option-name">{value}×{value===1?' · 正常':''}</span><span className="picker-check-slot"><Menu.ItemIndicator><span className="picker-check" aria-hidden="true">✓</span></Menu.ItemIndicator></span></Menu.RadioItem>)}</Menu.RadioGroup>
     </Menu.Content></Menu.Portal>
    </Menu.Root>
    <button type="button" className="player-control" aria-label={fullscreen?'退出全屏':'全屏'} title="全屏 (F)" onClick={onFullscreen}><Icon name="fullscreen"/></button>
   </div>
  </div>;
}
/** Outside the video/fullscreen target; never part of the immersive overlay. */
export function JumpControls({state,available,onSeek}:{state:PlaybackState;available:boolean;onSeek:(seconds:number)=>void}){
 return <div className="player-jumps" role="group" aria-label="当前分段快退快进">{MINUTE_JUMPS.map(([delta,label,description])=><button type="button" key={delta} data-player-jump={delta} aria-label={description} title={description} disabled={!available||!state.ready} onClick={()=>onSeek(state.time+delta)}><Icon name={delta<0?'rewind':'forward'}/><span>{label}</span></button>)}</div>;
}
