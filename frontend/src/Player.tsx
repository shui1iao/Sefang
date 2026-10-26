import {useCallback,useEffect,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {clampVolume,formatDuration,nextSegment,segmentSummary,type Group} from './segments';
import {PlayerControls,JumpControls,emptyPlayback} from './PlayerControls';
import {segmentSeek} from './player-controls';
import {keyAction,targetKind} from './keyboard';

function PlayerMessage({title,children,action}:{title:string;children?:ReactNode;action?:ReactNode}){return <div className="message" role="status"><span className="message-mark" aria-hidden="true">◌</span><strong>{title}</strong>{children&&<p>{children}</p>}{action}</div>}
/** One stable native video. Standalone controls never own src, play promises or ended. */
export function Player({video,group,index,onSegment}:{video:{cover:string};group:Group;index:number;onSegment:(index:number)=>void}){
 const ref=useRef<HTMLVideoElement>(null),area=useRef<HTMLDivElement>(null);const [poster]=useState(video.cover);
 const part=group.parts[index]??group.parts[0],multi=group.parts.length>1;
 const epoch=useRef(0),started=useRef(false),pending=useRef(false),endedEpoch=useRef(-1),alive=useRef(true),toastTimer=useRef(0);
 const live=useRef({group,index,onSegment});live.current={group,index,onSegment};
 const [error,setError]=useState(''),[blocked,setBlocked]=useState(''),[notice,setNotice]=useState(''),[toast,setToast]=useState('');
 const [playback,setPlayback]=useState(emptyPlayback),[rate,setRate]=useState(1),[isFullscreen,setFullscreen]=useState(false);
 const preferredRate=useRef(1),settingsOpen=useRef(false);
 const menuOpen=useCallback((open:boolean)=>{settingsOpen.current=open},[]);
 const sync=useCallback(()=>{const el=ref.current;if(!el)return;const ready=el.readyState>=1&&Number.isFinite(el.duration)&&el.duration>0;
  setPlayback({time:Number.isFinite(el.currentTime)?el.currentTime:0,duration:ready?el.duration:NaN,ready,paused:el.paused,ended:el.ended,loading:el.readyState<3,volume:el.volume,muted:el.muted,buffered:Array.from({length:el.buffered.length},(_,i)=>[el.buffered.start(i),el.buffered.end(i)])});
 },[]);
 const seek=useCallback((requested:number)=>{const el=ref.current;if(!el||el.readyState<1||!live.current.group.parts[live.current.index]?.available)return;const next=segmentSeek(el.currentTime,requested,el.duration);if(!next)return;
  pending.current=false;if(next.stop)el.pause();el.currentTime=next.time;sync();
 },[sync]);
 const volume=useCallback((value:number)=>{const el=ref.current;if(!el||!Number.isFinite(value))return;el.volume=clampVolume(value,0);if(value>0)el.muted=false;sync()},[sync]);
 const mute=useCallback(()=>{const el=ref.current;if(el){el.muted=!el.muted;sync()}},[sync]);
 function changeRate(value:number){const el=ref.current;if(!el)return;preferredRate.current=value;el.defaultPlaybackRate=value;el.playbackRate=value;setRate(value)}
 function rateChanged(){const el=ref.current;if(!el||!Number.isFinite(el.playbackRate)||el.playbackRate<=0)return;preferredRate.current=el.playbackRate;if(el.defaultPlaybackRate!==el.playbackRate)el.defaultPlaybackRate=el.playbackRate;setRate(el.playbackRate);sync()}
 function metadata(){const el=ref.current;if(el){el.defaultPlaybackRate=preferredRate.current;el.playbackRate=preferredRate.current}sync()}
 const say=useCallback((text:string)=>{setToast(text);window.clearTimeout(toastTimer.current);toastTimer.current=window.setTimeout(()=>{if(alive.current)setToast('')},1800)},[]);
 // Original play promise/epoch rules: no stale segment promise can change a later segment.
 const attempt=useCallback((label:string)=>{const el=ref.current,current=epoch.current;if(!el||!el.getAttribute('src'))return;
  el.play().then(()=>{if(alive.current&&current===epoch.current)setBlocked('')},(reason:unknown)=>{if(!alive.current||current!==epoch.current)return;const name=reason instanceof DOMException?reason.name:'';
   if(name==='NotAllowedError')setBlocked(label);else if(name!=='AbortError'){pending.current=false;setError('本段暂时无法播放：浏览器未能读取或解码此段。已停在当前段，不会自动跳段。')}});
 },[]);
 const toggle=useCallback(()=>{const el=ref.current;if(!el)return;if(el.paused||el.ended){setBlocked('');attempt('点击播放')}else el.pause()},[attempt]);
 const fullscreen=useCallback(()=>{
  const el=ref.current,box=area.current;if(!el||!box)return;
  if(document.fullscreenElement){document.exitFullscreen().catch(()=>say('浏览器未允许退出全屏'));return}
  const legacy=()=>{const v=el as HTMLVideoElement&{webkitEnterFullscreen?:()=>void};if(typeof v.webkitEnterFullscreen==='function'){try{v.webkitEnterFullscreen()}catch{say('浏览器拒绝了全屏请求')}}else say('当前浏览器不支持网页全屏')};
  if(typeof box.requestFullscreen==='function'&&document.fullscreenEnabled!==false)box.requestFullscreen().catch(legacy);else legacy();
 },[say]);
 const actions=useRef({toggle,fullscreen,seek,volume,mute});actions.current={toggle,fullscreen,seek,volume,mute};
 useLayoutEffect(()=>{epoch.current++;setError('');setBlocked('');setNotice('');const el=ref.current;setPlayback({...emptyPlayback,volume:el?.volume??1,muted:el?.muted??false});if(el){el.defaultPlaybackRate=preferredRate.current;el.playbackRate=preferredRate.current}if(pending.current){pending.current=false;attempt('点击继续下一段')}},[part.stream,attempt]);
 useEffect(()=>{alive.current=true;const el=ref.current;let previous:Element|null=null;
  function onKey(e:KeyboardEvent){
   // Respect actual shadow-input focus, buttons and Radix menu navigation/typeahead.
   if(settingsOpen.current)return;const target=e.composedPath()[0]??e.target;
   const action=keyAction(e,targetKind(target as EventTarget|null));const media=ref.current;if(!media?.isConnected||!action)return;
   e.preventDefault();e.stopPropagation();if(action.kind==='toggle')actions.current.toggle();else if(action.kind==='fullscreen')actions.current.fullscreen();else if(action.kind==='seek')actions.current.seek(media.currentTime+action.delta);else if(action.kind==='volume')actions.current.volume(clampVolume(media.volume,action.delta));else if(action.kind==='mute')actions.current.mute();
  }
  function entered(){setFullscreen(true);el?.focus({preventScroll:true})}
  function exited(){setFullscreen(false)}
  function fs(){const current=document.fullscreenElement;setFullscreen(current===area.current||current===el);if(current!==previous&&(current===el||current===area.current))entered();previous=current}
  window.addEventListener('keydown',onKey,true);document.addEventListener('fullscreenchange',fs);el?.addEventListener('webkitbeginfullscreen',entered);el?.addEventListener('webkitendfullscreen',exited);
  return()=>{alive.current=false;window.clearTimeout(toastTimer.current);window.removeEventListener('keydown',onKey,true);document.removeEventListener('fullscreenchange',fs);el?.removeEventListener('webkitbeginfullscreen',entered);el?.removeEventListener('webkitendfullscreen',exited);if(el){el.pause();el.removeAttribute('src');el.load()}};
 },[]);
 function ended(){const el=ref.current;if(!el||!el.ended||endedEpoch.current===epoch.current)return;endedEpoch.current=epoch.current;
  if(!started.current)return;const {group:current,index:position,onSegment:go}=live.current;const step=nextSegment(current,position);
  if('next'in step){pending.current=true;go(step.next)}else if(current.parts.length>1)setNotice(step.stop==='last'?'全片已播放完最后一段':'下一段当前不可用，已停在本段；可手动选择其他分段。');
 }
 function failed(){if(!ref.current?.error)return;pending.current=false;setBlocked('');setError(multi?`第${live.current.index+1}段暂时无法播放：可能是网络中断、线路未取得、原消息已下架或浏览器不支持此编码。已停在本段，不会自动跳到其他段。`:'视频暂时无法播放。可能已失效、线路未取得或浏览器不支持此编码。请返回列表选择其他视频。')}
 function retry(){const el=ref.current;if(!el)return;epoch.current++;setError('');el.load();if(started.current)attempt('点击播放')}
 function select(position:number){if(position===index)return;pending.current=started.current;onSegment(position)}
 return <><div className="player-area" ref={area} data-player="" tabIndex={-1} aria-label="视频播放器">
  <div className="player-surface"><video ref={ref} data-main-video="" tabIndex={-1} playsInline preload="metadata" autoPlay={false} poster={poster} src={part.available?part.stream:undefined} data-segment-index={index}
   onLoadedMetadata={metadata} onDurationChange={sync} onTimeUpdate={sync} onProgress={sync} onPause={sync} onSeeking={sync} onSeeked={sync} onWaiting={sync} onCanPlay={sync} onVolumeChange={sync} onRateChange={rateChanged} onEmptied={()=>setPlayback(state=>({...state,time:0,duration:NaN,ready:false,paused:true,ended:false,buffered:[]}))}
   onPlaying={()=>{started.current=true;setBlocked('');setNotice('');sync()}} onEnded={()=>{sync();ended()}} onError={failed}/>
  {part.available&&!error&&playback.paused&&<button type="button" className="player-center-play" data-player-center-play="" aria-label="播放视频" title="播放视频" onClick={toggle}><svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor"><path d="m8 5 11 7-11 7Z"/></svg></button>}
  {toast&&<div className="player-toast" role="status" aria-live="polite">{toast}</div>}
  <PlayerControls state={playback} rate={rate} available={part.available&&!error} fullscreen={isFullscreen} area={area} onToggle={toggle} onSeek={seek} onVolume={volume} onMute={mute} onRate={changeRate} onFullscreen={fullscreen} onMenuOpen={menuOpen}/>
  </div>
  {blocked&&!error&&<p className="player-notice" role="status">{blocked}：请使用播放按钮继续。</p>}
  {!part.available?<PlayerMessage title="本段不可用">原消息已删除或当前账号无权限；可选择其他分段。</PlayerMessage>:error?<PlayerMessage title="播放未完成" action={<button type="button" onClick={retry}>重试本段</button>}>{error}</PlayerMessage>:null}
  {notice&&<p className="player-notice" role="status">{notice}</p>}
 </div>
 {!isFullscreen&&<JumpControls state={playback} available={part.available&&!error} onSeek={seek}/>}
 {multi&&<div className="segment-bar" data-segment-bar=""><p className="segment-summary" data-segment-summary="">{segmentSummary(group,index)}</p><div className="segment-list" role="group" aria-label="选择分段">{group.parts.map((p,i)=><button key={p.message_id} type="button" data-segment={i+1} className={'segment'+(i===index?' current':'')} aria-current={i===index?'true':undefined} disabled={!p.available} onClick={()=>select(i)}>第{i+1}段 · {formatDuration(p.duration)}{p.available?'':' · 不可用'}</button>)}</div></div>}
 </>;
}
