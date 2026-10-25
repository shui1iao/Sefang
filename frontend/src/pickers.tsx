import {useEffect,useId,useRef,useState,type RefObject} from 'react';
import * as Menu from '@radix-ui/react-dropdown-menu';
import {Link} from 'react-router';
import {labels,type Kind} from './navigation';
import {displayName,nameHint} from './display';
import {facetItems,SORT_OPTIONS,type FacetEntity} from './facet-model';

type EntityPage={items:FacetEntity[];total:number;page:number;pages:number};
async function readJson<T>(url:string,signal:AbortSignal):Promise<T>{
 const response=await fetch(url,{signal});
 if(!response.ok)throw Error(response.status===404?'此条目未取得':'读取未完成，请重试');
 return response.json();
}
/** Initially one page; expand, search or horizontal interaction requests the remaining pages once. */
function useCatalog(kind:Kind,requested:boolean){
 const first=useRef<EntityPage|null>(null);
 const complete=useRef<FacetEntity[]|null>(null);
 const [revision,setRevision]=useState(0);
 const [state,setState]=useState<{items:FacetEntity[];total:number|null;complete:boolean;error:string;loading:boolean}>({items:[],total:null,complete:false,error:'',loading:true});
 useEffect(()=>{
  const control=new AbortController();
  setState(s=>({...s,error:'',loading:true}));
  async function load(){
   const page=first.current??await readJson<EntityPage>(`/api/entities/${kind}?limit=100&page=1`,control.signal);
   if(control.signal.aborted)return;
   first.current=page;
   if(!Number.isInteger(page.pages)||page.pages<0||page.pages>10000)throw Error('目录页数未取得，请重试');
   if(complete.current){setState({items:complete.current,total:page.total,complete:true,error:'',loading:false});return}
   const items=[...page.items];
   setState({items,total:page.total,complete:page.pages<=1,error:'',loading:requested&&page.pages>1});
   if(requested){
    for(let p=2;p<=page.pages;p++){
     const next=await readJson<EntityPage>(`/api/entities/${kind}?limit=100&page=${p}`,control.signal);
     if(control.signal.aborted)return;
     items.push(...next.items);
    }
    if(new Set(items.map(e=>e.id)).size!==page.total)throw Error('目录已变化，请重试读取');
    complete.current=items;
    setState({items,total:page.total,complete:true,error:'',loading:false});
   }
  }
  load().catch(error=>{if(!control.signal.aborted)setState(s=>({...s,error:error.message,loading:false}))});
  return()=>control.abort();
 },[kind,requested,revision]);
 return {...state,retry:()=>{first.current=null;complete.current=null;setRevision(n=>n+1)}};
}
function useSelected(kind:Kind,value:string){
 const [state,setState]=useState<{id:string;entity?:FacetEntity;error?:string}>({id:''});
 const [revision,setRevision]=useState(0);
 useEffect(()=>{
  if(!value)return;
  const control=new AbortController();setState({id:value});
  readJson<FacetEntity>(`/api/entities/${kind}/${encodeURIComponent(value)}`,control.signal).then(entity=>{if(!control.signal.aborted)setState({id:value,entity})}).catch(error=>{if(!control.signal.aborted)setState({id:value,error:error.message})});
  return()=>control.abort();
 },[kind,value,revision]);
 return {...(state.id===value?state:{}),retry:()=>setRevision(n=>n+1)};
}
function restoreTrigger(event:Event,trigger:RefObject<HTMLButtonElement|null>){event.preventDefault();trigger.current?.focus({preventScroll:true})}
function Chevron(){return <svg className="picker-chevron" aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="m4 6 4 4 4-4"/></svg>}
function Check(){return <span className="picker-check" aria-hidden="true">✓</span>}
export function FacetStrip({kind,value,onChange}:{kind:'categories'|'studios';value:string;onChange:(value:string)=>void}){
 const [requested,setRequested]=useState(false),[expanded,setExpanded]=useState(false),[query,setQuery]=useState('');
 const catalog=useCatalog(kind,requested),selected=useSelected(kind,value),label=labels[kind],id=useId();
 const selectedId=kind==='categories'?(selected.entity?.id??value):value;
 const current=catalog.items.find(e=>e.id===selectedId)??selected.entity;
 const matches=facetItems(catalog.items,query,'count');
 const selectedButton=useRef<HTMLButtonElement>(null);
 useEffect(()=>{const node=selectedButton.current,parent=node?.parentElement;if(!node||!parent||expanded)return;const box=node.getBoundingClientRect(),row=parent.getBoundingClientRect();if(box.left<row.left||box.right>row.right)parent.scrollLeft+=box.left-row.left-2},[value,current?.id,catalog.items.length,expanded]);
 return <section className="facet-section" data-facet={kind} aria-label={'按'+label+'筛选'}>
  <div className="facet-heading"><div className="facet-label"><strong>选择{label}</strong><LinkToDirectory kind={kind}/></div>
   <div className="facet-search"><input aria-label={'搜索'+label+'名称'} placeholder={'搜索'+label+' / 原名'} maxLength={200} value={query} onFocus={()=>setRequested(true)} onChange={e=>{setRequested(true);setQuery(e.target.value)}}/>{query&&<button type="button" aria-label={'清空'+label+'搜索'} onClick={()=>setQuery('')}>×</button>}</div>
   <button className="quiet facet-expand" type="button" aria-expanded={expanded} aria-controls={id} onClick={()=>{setRequested(true);setExpanded(v=>!v)}}>{expanded?'收起'+label:'展开全部'+label}</button>
  </div>
  {value&&<div className="facet-selection" data-facet-selection="" role="status"><span title={current?nameHint(current):value}>已选：{current?displayName(current):selected.error?'名称未取得':'正在读取…'}</span><button type="button" onClick={()=>onChange('')}>清除{label}</button>{selected.error&&!current&&<button type="button" onClick={selected.retry}>重试名称</button>}</div>}
  <div id={id} className={'facet-strip'+(expanded?' expanded':'')} role="group" aria-label={label+'选项'} onScroll={()=>setRequested(true)}>
   <button type="button" className={'facet-choice'+(!value?' selected':'')} aria-pressed={!value} data-entity-option="" onClick={()=>onChange('')}>全部{label}</button>
   {matches.map(entity=><button type="button" ref={selectedId===entity.id?selectedButton:undefined} key={entity.id} data-entity-option={entity.id} className={'facet-choice'+(selectedId===entity.id?' selected':'')} aria-pressed={selectedId===entity.id} title={nameHint(entity)} onClick={()=>onChange(entity.id)}>{displayName(entity)}<small>{entity.count}</small></button>)}
  </div>
  <div className="facet-status">{catalog.error?<span role="alert">{catalog.error} <button type="button" onClick={catalog.retry}>重试</button></span>:catalog.loading?<span role="status">正在读取{requested?'完整':''}{label}目录…</span>:<span>{catalog.complete?`${matches.length} / ${catalog.total}`:`已显示 ${matches.length} / ${catalog.total??'…'}`} 个{label}{!catalog.complete&&' · 搜索或展开可读取全部'}</span>}{catalog.complete&&!matches.length&&<span role="status">没有匹配的{label}，试试其他名称。</span>}</div>
 </section>;
}
function LinkToDirectory({kind}:{kind:Kind}){return <Link to={'/'+kind}>{labels[kind]}目录 <span aria-hidden="true">↗</span></Link>}
export function SortPicker({value,onChange}:{value:string;onChange:(value:string)=>void}){
 const [open,setOpen]=useState(false);
 const triggerRef=useRef<HTMLButtonElement>(null);
 const name=SORT_OPTIONS.find(e=>e[0]===value)?.[1]??SORT_OPTIONS[0][1];
 const trigger=<button type="button" ref={triggerRef} className="picker-trigger sort-trigger" aria-label="排序"><span className="picker-value">{name}</span><Chevron/></button>;
 function choose(next:string){onChange(next);setOpen(false)}
 return <div className="sort picker-sort"><span>排序</span>{<Menu.Root open={open} onOpenChange={setOpen} modal={false}>
  <Menu.Trigger asChild>{trigger}</Menu.Trigger><Menu.Portal><Menu.Content className="picker-layer picker-menu" data-picker-layer="menu" sideOffset={8} collisionPadding={12} avoidCollisions loop onCloseAutoFocus={event=>restoreTrigger(event,triggerRef)}>
   <Menu.Label className="picker-menu-label">排序方式</Menu.Label><Menu.RadioGroup value={value} onValueChange={choose}>{SORT_OPTIONS.map(([key,text])=><Menu.RadioItem className="picker-option" key={key} value={key}><span className="picker-option-name">{text}</span><span className="picker-check-slot"><Menu.ItemIndicator><Check/></Menu.ItemIndicator></span></Menu.RadioItem>)}</Menu.RadioGroup>
  </Menu.Content></Menu.Portal>
 </Menu.Root>}</div>;
}
