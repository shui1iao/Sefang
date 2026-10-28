export type TranslationInfo={state:string;method:string};
export type Named={name:string;name_original?:string;display_name?:string;name_zh?:string|null;name_translation?:TranslationInfo};
export type Titled={title:string;code?:string;display_title?:string;title_zh?:string|null;title_translation?:TranslationInfo};
export const displayName=(item:Named)=>item.display_name||item.name;
export function displayTitle(item:Titled){
 const title=item.display_title?.trim()?item.display_title:item.title;
 const code=item.code?.trim();if(!code)return title;
 // DTO.code is already identified/canonical. Only remove this same number for display;
 // never infer a number from a title or change original text, translation or search data.
 const spelling=code.replace(/[.*+?^${}()|[\]\\]/g,'\\$&').replace(/-/g,'[-_ ]?');
 const same=new RegExp(`(^|[^a-z0-9])${spelling}(?![a-z0-9])`,'gi');
 const name=title.replace(same,(_match,lead:string)=>lead).replace(/\(\s*\)|（\s*）|\[\s*\]|【\s*】/g,'').replace(/^[\s·・|:：\-–—]+|[\s·・|:：\-–—]+$/g,'');
 return name?`${code} · ${name}`:code;
}
export function translationLabel(info?:TranslationInfo){
 if(info?.method==='machine')return '机翻，非官方中文';
 if(info?.method==='dictionary')return '中文释义';
 if(info?.method==='normalized_unverified')return '简体规范，原语言未确认';
 return '';
}
export const nameHint=(item:Named)=>item.name_original!==undefined?item.name_original:item.name_translation?.method==='actor_alias'?`${displayName(item)} · 同一演员`:item.name_translation?.method==='actor_original'?item.name:[translationLabel(item.name_translation),`原名：${item.name}`].filter(Boolean).join(' · ');
export const titleHint=(item:Titled)=>[translationLabel(item.title_translation),`原标题：${item.title}`].filter(Boolean).join(' · ');
