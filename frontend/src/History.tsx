import {useEffect,useState,type MouseEvent} from 'react';
import {Link,useLocation,useNavigate} from 'react-router';
import {useData,useScroll} from './hooks';
import {currentSession,writeJson} from './auth-client';
import {Loading,Message,Pages} from './components';
import {displayTitle} from './display';
import {formatDuration} from './segments';
import type {Video,Page} from './types';
export type HistoryRow={id:string;work_id:string;title:string;video:Video|null;part_number:number|null;position:number;duration:number;completed:boolean;updated_at:number;available:boolean;note:string;channel_id:number|null;message_id:number|null};
export function historyTitle(video:Video|null){
 if(!video)return {code:'',text:'作品资料当前不可用'};
 const code=video.code?.trim()||'';
 // Both DTO title and display_title may fall back to the original message
 // filename. Only history suppresses explicit media filenames; never strip an
 // extension to invent a work title or mutate metadata used elsewhere.
 const filename=/\.(?:mp4|m4v|mkv|webm|mov|mpg|mpeg|mpe|m1v|m2v|3gp|3g2|avi|wmv|flv|ts|mts|m2ts|ogv)$/i;
 const candidate=[video.display_title,video.title].find(value=>typeof value==='string'&&value.trim()&&!filename.test(value.trim()));
 if(!candidate)return {code,text:'作品标题暂未取得'};
 const title=displayTitle({title:candidate,code});
 return {code,text:(code&&title.startsWith(code)?title.slice(code.length).replace(/^\s*·\s*/,''):title)||'作品标题暂未取得'};
}
function HistoryTitle({video}:{video:Video|null}){const {code,text}=historyTitle(video);return <>{code&&<><span className="watch-code">{code}</span>{text&&' · '}</>}{text}</>}
export function History(){
 const loc=useLocation(),navigate=useNavigate();const input=Number(new URLSearchParams(loc.search).get('page')||1);const page=Number.isSafeInteger(input)&&input>0?input:1;
 const account=currentSession()?.id;
 const data=useData<Page<HistoryRow>>('/api/history?page='+page);
 const [confirm,setConfirm]=useState(''),[error,fail]=useState(''),[busy,setBusy]=useState(false);
 const root=useScroll(!data.loading);
 useEffect(()=>{setConfirm('');fail('')},[loc.key]);
 async function remove(id:string){setBusy(true);fail('');try{await writeJson(id==='all'?'/api/history/clear':`/api/history/${id}/delete`,{});if(account!==currentSession()?.id)return;setConfirm('');if(page>1&&data.data?.items.length===1)navigate('/history?page='+(page-1),{replace:true});else data.retry()}catch(e){fail(e instanceof Error?e.message:'操作未完成')}finally{setBusy(false)}}
 return <main className="container history-page" ref={root} data-history-page=""><div className="history-title"><div><h1>播放历史</h1><p className="muted">仅你可见 · 从历史恢复分段与位置，不自动播放</p></div>{!!data.data?.total&&<button type="button" disabled={busy} onClick={()=>setConfirm('all')}>清空历史</button>}</div>
 {error&&<p role="alert">{error}</p>}
 {confirm==='all'&&<section className="history-confirm" role="alert"><p>确认清空你的全部播放历史？此操作无法撤销。</p><p className="muted">已打开播放器的旧记录不会恢复；重新打开作品并播放后才会再次记录。</p><button disabled={busy} className="primary-button" onClick={()=>remove('all')}>确认清空</button><button onClick={()=>setConfirm('')}>取消</button></section>}
 {data.loading?<Loading/>:data.error?<Message title="历史未取得" action={<button onClick={data.retry}>重试</button>}>{data.error}</Message>:!data.data?.total?<Message title="还没有播放历史">实际开始播放后会保存在这里。打开详情或预览不会记录。</Message>:<><p className="muted">共 {data.data.total} 部作品 · 按最近播放排序</p><div className="history-list">{data.data.items.map(row=>{
 const link={to:row.available?`/watch/${row.channel_id}/${row.message_id}?resume=${row.id}`:'#','aria-disabled':!row.available,onClick:(event:MouseEvent<HTMLAnchorElement>)=>{if(!row.available)event.preventDefault()},state:{from:'/history'+loc.search}};
 const title=Object.values(historyTitle(row.video)).filter(Boolean).join(' · ');
 return <article key={row.id} className="history-card" data-history-id={row.id}>
 <Link className="history-art" {...link} aria-label={(row.available?'继续观看：':'当前不可用：')+title}>{row.video&&<img src={row.video.cover} alt="" loading="lazy" onError={e=>{e.currentTarget.style.display='none'}}/>}<span>{row.available?'继续观看':'当前不可用'}</span></Link>
 <div className="history-info"><Link className="history-content" {...link}><h2><HistoryTitle video={row.video}/></h2><p>第{row.part_number??'—'}段 · {formatDuration(row.position)} / {formatDuration(row.duration)}{row.completed?' · 已看完':''}</p></Link>
 <div className="history-meta"><Link className="history-details" {...link}><p className="muted">{new Date(row.updated_at).toLocaleString('zh-CN')}</p>{row.note&&<p className="muted">{row.note}</p>}</Link>
 <div className="history-delete">{confirm===row.id?<><p>确认删除此条历史？</p><p className="muted">重新打开本作品并播放后才会再次记录。</p><button disabled={busy} onClick={()=>remove(row.id)}>确认删除</button><button onClick={()=>setConfirm('')}>取消</button></>:<button disabled={busy} onClick={()=>setConfirm(row.id)} aria-label={'删除历史：'+title}>删除</button>}</div></div></div></article>})}</div><Pages page={data.data.page} pages={data.data.pages}/></>}
 </main>
}
