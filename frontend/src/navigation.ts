export const KINDS=['actors','studios','categories'] as const;
export type Kind=typeof KINDS[number];
export const labels:Record<Kind,string>={actors:'演员',studios:'发行商',categories:'分类'};
export function safeLink(value:unknown):string|null {
 if(typeof value!=='string'||value.length>4096)return null;
 try {const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password&&url.hostname.includes('.')&&!/^(?:\d+\.){3}\d+$/.test(url.hostname)?url.href:null}catch{return null}
}
export function normalizeQuery(search:string):URLSearchParams {
 const input=new URLSearchParams(search),out=new URLSearchParams();
 for(const name of ['actor','studio','category']) {const value=input.get(name)||'';if(/^[0-9a-f]{24}$/.test(value))out.set(name,value)}
 const q=(input.get('q')||'').slice(0,300);if(q)out.set('q',q);
 const sort=input.get('sort');if(sort&&['oldest','release','name','duration'].includes(sort))out.set('sort',sort);
 const page=input.get('page')||'';if(/^\d{1,6}$/.test(page)&&Number(page)>1)out.set('page',String(Math.min(100000,Number(page))));
 return out;
}
export function filterKey(kind:Kind){return ({actors:'actor',studios:'studio',categories:'category'} as const)[kind]}
export function listLink(patch:Record<string,string>,search=''){const p=normalizeQuery(search);for(const [key,value]of Object.entries(patch)){if(value)p.set(key,value);else p.delete(key)}p.delete('page');return '/'+(p.size?'?'+normalizeQuery(p.toString()):'')}
export function validWatch(cid:string,mid:string){return [cid,mid].every(v=>/^[1-9]\d{0,15}$/.test(v)&&Number.isSafeInteger(Number(v)))}
/** 段间切换用replace：只带上原列表from和分段标记，后退一次仍回原列表（筛选/页码/滚动）。 */
export function segmentState(state:unknown){const from=state&&typeof state==='object'?(state as {from?:unknown}).from:undefined;return {...(typeof from==='string'?{from}:{}),segment:true as const}}
export function safeReturn(value:unknown){if(typeof value!=='string'||value.length>16000)return '/';try{const url=new URL(value,location.origin);return url.origin===location.origin&&(/^\/$|^\/(actors|studios|categories)(\/[0-9a-f]{24})?$/.test(url.pathname))?url.pathname+(url.search?'?'+normalizeQuery(url.search):''):'/'}catch{return '/'}}

/** Facets leave entity routes for the canonical list, preserving their effective implicit filter. */
export function facetLink(search:string,key:'category'|'studio',value:string,binding?:{kind:Kind;id:string}){
 const effective=normalizeQuery(search);
 if(binding)effective.set(filterKey(binding.kind),binding.id);
 return listLink({[key]:value},effective.toString());
}
