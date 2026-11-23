import {createElement,useEffect,useLayoutEffect,useRef,useState,type CSSProperties,type RefObject} from 'react';
import * as Menu from '@radix-ui/react-dropdown-menu';
// A standalone UI element only: importing the controller/React barrel creates probe media.
import 'media-chrome/media-time-range.js';
import {PLAYBACK_RATES,MINUTE_JUMPS,playerTime} from './player-controls';
import {useFullscreenControls} from './useFullscreenControls';
import {Check} from './pickers';

export type PlaybackState={time:number;duration:number;ready:boolean;paused:boolean;ended:boolean;loading:boolean;volume:number;muted:boolean;buffered:number[][]};
export const emptyPlayback:PlaybackState={time:0,duration:NaN,ready:false,paused:true,ended:false,loading:false,volume:1,muted:false,buffered:[]};
type TimelineElement=HTMLElement&{mediaCurrentTime:number;mediaDuration:number;mediaSeekable:number[]|undefined;mediaBuffered:number[][];mediaPaused:boolean;mediaEnded:boolean;mediaLoading:boolean;mediaPlaybackRate:number};
function Timeline({state,rate,onSeek}:{state:PlaybackState;rate:number;onSeek:(seconds:number)=>void}){
 const ref=useRef<TimelineElement|null>(null),action=useRef(onSeek);action.current=onSeek;
 useEffect(()=>{const el=ref.current;if(!el)return;const seek=(event:Event)=>action.current(Number((event as CustomEvent<number>).detail));el.addEventListener('mediaseekrequest',seek);return()=>el.removeEventListener('mediaseekrequest',seek)},[]);
 useLayoutEffect(()=>{const el=ref.current;if(!el)return;Object.assign(el,{mediaCurrentTime:state.time,mediaDuration:state.duration,mediaSeekable:state.ready?[0,state.duration]:undefined,mediaBuffered:state.buffered,mediaPaused:state.paused,mediaEnded:state.ended,mediaLoading:state.loading,mediaPlaybackRate:rate});el.toggleAttribute('disabled',!state.ready);if(state.ready)el.removeAttribute('aria-disabled');else el.setAttribute('aria-disabled','true')},[state,rate]);
 return createElement('media-time-range',{ref,className:'player-timeline','aria-label':'播放进度','data-player-timeline':''});
}
/** Transport glyphs: filled play/pause read at a glance over moving video; outline for secondary controls. */
function Icon({name}:{name:'play'|'pause'|'muted'|'volume'|'fullscreen'|'exit'|'rewind'|'forward'}){
 const paths={rewind:<path d="M11 6.5 4.5 12l6.5 5.5ZM19.5 6.5 13 12l6.5 5.5Z"/>,forward:<path d="M4.5 6.5 11 12l-6.5 5.5ZM13 6.5l6.5 5.5-6.5 5.5Z"/>,play:<path className="glyph-fill" d="M7.5 5.2v13.6a.8.8 0 0 0 1.2.7l11-6.8a.8.8 0 0 0 0-1.4l-11-6.8a.8.8 0 0 0-1.2.7Z"/>,pause:<path className="glyph-fill" d="M7 5h3v14H7zM14 5h3v14h-3z"/>,muted:<><path d="M11 5 6.5 9H3.5v6h3l4.5 4Z"/><path d="m16 9.5 5 5m0-5-5 5"/></>,volume:<><path d="M11 5 6.5 9H3.5v6h3l4.5 4Z"/><path d="M15 9a4.2 4.2 0 0 1 0 6m2.8-9a8.4 8.4 0 0 1 0 12"/></>,fullscreen:<path d="M4 9V5a1 1 0 0 1 1-1h4m6 0h4a1 1 0 0 1 1 1v4M4 15v4a1 1 0 0 0 1 1h4m6 0h4a1 1 0 0 0 1-1v-4"/>,exit:<path d="M9 4v4a1 1 0 0 1-1 1H4m16 0h-4a1 1 0 0 1-1-1V4M4 15h4a1 1 0 0 1 1 1v4m6 0v-4a1 1 0 0 1 1-1h4"/>};
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
     <input type="range" aria-label="音量" min="0" max="1" step="0.05" value={state.muted?0:state.volume} style={{'--volume':state.muted?0:state.volume} as CSSProperties} onChange={event=>onVolume(Number(event.target.value))}/>
    </div>
    <Menu.Root open={open} onOpenChange={menu} modal={false}>
     <Menu.Trigger asChild><button type="button" className="player-control player-settings-trigger" aria-label="播放倍速" title="播放倍速"><span>{rate}×</span></button></Menu.Trigger>
     <Menu.Portal container={fullscreen?area.current:undefined}><Menu.Content className="picker-layer picker-menu player-settings-menu" data-player-settings="" side={fullscreen?'top':'bottom'} align="end" sideOffset={8} collisionPadding={8} avoidCollisions loop>
      <Menu.Label className="picker-menu-label">播放速度</Menu.Label><Menu.RadioGroup value={String(rate)} onValueChange={value=>{onRate(Number(value));menu(false)}} aria-label="播放速度">{PLAYBACK_RATES.map(value=><Menu.RadioItem className="picker-option" key={value} value={String(value)} data-player-rate={value}><span className="picker-option-name">{value}×{value===1?' · 正常':''}</span><span className="picker-check-slot"><Menu.ItemIndicator><Check/></Menu.ItemIndicator></span></Menu.RadioItem>)}</Menu.RadioGroup>
     </Menu.Content></Menu.Portal>
    </Menu.Root>
    <button type="button" className="player-control" aria-label={fullscreen?'退出全屏':'全屏'} title="全屏 (F)" onClick={onFullscreen}><Icon name={fullscreen?'exit':'fullscreen'}/></button>
   </div>
  </div>;
}
/** Outside the video/fullscreen target; never part of the immersive overlay. */
export function JumpControls({state,available,onSeek}:{state:PlaybackState;available:boolean;onSeek:(seconds:number)=>void}){
 return <div className="player-jumps" role="group" aria-label="当前分段快退快进">{MINUTE_JUMPS.map(([delta,label,description])=><button type="button" key={delta} data-player-jump={delta} aria-label={description} title={description} disabled={!available||!state.ready} onClick={()=>onSeek(state.time+delta)}><Icon name={delta<0?'rewind':'forward'}/><span>{label}</span></button>)}</div>;
}
