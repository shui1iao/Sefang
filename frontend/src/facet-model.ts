import type {Named} from './display';
export type FacetEntity=Named&{id:string;count:number;aliases?:string[]};
export type FacetOrder='count'|'name';
const folded=(text:string)=>text.normalize('NFKC').toLocaleLowerCase().trim();
export function facetItems<T extends FacetEntity>(items:T[],query:string,order:FacetOrder):T[]{
 const q=folded(query);
 return items.filter(item=>folded(item.name).includes(q)||folded(item.name_zh||item.display_name||'').includes(q)||(item.aliases||[]).some(name=>folded(name).includes(q))).sort((a,b)=>(order==='count'?b.count-a.count:0)||a.name.localeCompare(b.name,'ja')||a.id.localeCompare(b.id));
}
export function moveOption(key:string,index:number,length:number):number|null{
 if(!length)return null;
 if(key==='Home')return 0;
 if(key==='End')return length-1;
 if(key==='ArrowDown')return (index+1+length)%length;
 if(key==='ArrowUp')return (index-1+length)%length;
 return null;
}
export function isComposing(event:{isComposing?:boolean;keyCode?:number}){return !!event.isComposing||event.keyCode===229}
