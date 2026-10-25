import {normalizeQuery} from './navigation';
/** Integers only; never navigate to an empty page outside this result set. */
export function jumpPage(value:string,pages:number):number|null {
 const text=value.normalize('NFKC').trim();
 if(!/^[+-]?\d+$/.test(text)||!Number.isSafeInteger(pages)||pages<1)return null;
 const number=Number(text);if(Number.isNaN(number))return null;
 return Math.max(1,Math.min(pages,number));
}
export function pageHref(pathname:string,search:string,page:number){
 const query=normalizeQuery(search);if(page>1)query.set('page',String(page));else query.delete('page');
 return pathname+(query.size?'?'+query:'');
}
