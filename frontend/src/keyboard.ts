import {SEEK_STEP,VOLUME_STEP} from './segments';

export type KeyTarget='editable'|'slider'|'activatable'|'media'|'page';
export type PlayerAction={kind:'toggle'}|{kind:'seek';delta:number}|{kind:'volume';delta:number}|{kind:'mute'}|{kind:'fullscreen'}|{kind:'consume'};
export type KeyLike={key:string;code?:string;repeat?:boolean;ctrlKey?:boolean;metaKey?:boolean;altKey?:boolean;isComposing?:boolean;keyCode?:number;defaultPrevented?:boolean};

const EDITABLE='textarea,select,[contenteditable]:not([contenteditable="false"]),input:not([type=range]):not([type=button]):not([type=submit]):not([type=reset]):not([type=checkbox]):not([type=radio]):not([type=image]):not([type=color]):not([type=file])';
const ACTIVATABLE='button,a[href],summary,input,[role=button],[role=link],[role=tab],[role=menuitem],[role=checkbox],[role=option]';

/** 焦点所在控件：可编辑控件完全不拦截；滑杆保留方向键/空格；按钮链接保留空格激活。 */
export function targetKind(target:EventTarget|null):KeyTarget{
 if(typeof Element==='undefined'||!(target instanceof Element))return 'page';
 if(target.closest(EDITABLE))return 'editable';
 if(target.closest('input[type=range],[role=slider]'))return 'slider';
 if(typeof HTMLMediaElement!=='undefined'&&target instanceof HTMLMediaElement)return 'media';
 if(target.closest(ACTIVATABLE))return 'activatable';
 return 'page';
}

/** 纯决策：Space/K播放暂停、←/→ ±5秒、↑/↓音量、M静音、F全屏；返回null表示交还浏览器默认行为。 */
export function keyAction(event:KeyLike,target:KeyTarget):PlayerAction|null{
 if(event.defaultPrevented||event.isComposing||event.keyCode===229||event.ctrlKey||event.metaKey||event.altKey||target==='editable')return null;
 const key=event.key,code=event.code||'',lower=key.length===1?key.toLowerCase():key;
 const letter=(c:string)=>lower===c||code==='Key'+c.toUpperCase();
 const space=key===' '||key==='Spacebar';
 // 长按重复：Space/K/M/F只吃掉事件不重复切换；方向键每个事件只一步。
 const once=(action:PlayerAction):PlayerAction=>event.repeat?{kind:'consume'}:action;
 if(space){if(target==='activatable'||target==='slider')return null;return once({kind:'toggle'})}
 if(key==='ArrowLeft'||key==='ArrowRight'||key==='ArrowUp'||key==='ArrowDown'){
  if(target==='slider')return null;
  if(key==='ArrowLeft'||key==='ArrowRight')return {kind:'seek',delta:key==='ArrowLeft'?-SEEK_STEP:SEEK_STEP};
  return {kind:'volume',delta:key==='ArrowUp'?VOLUME_STEP:-VOLUME_STEP};
 }
 if(letter('k'))return once({kind:'toggle'});
 if(letter('m'))return once({kind:'mute'});
 if(letter('f'))return once({kind:'fullscreen'});
 return null;
}
