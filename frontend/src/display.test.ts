import {describe,it,expect} from 'vitest';
import {displayTitle,displayName,nameHint,titleHint,translationLabel} from './display';
describe('number-first display title only',()=>{
 it('prefixes canonical DTO code to translated or original title',()=>{
  expect(displayTitle({code:'FC2-PPV-4961775',title:'Original sample',display_title:'合成中文标题'})).toBe('FC2-PPV-4961775 · 合成中文标题');
  expect(displayTitle({code:'ABC-123',title:'Original sample'})).toBe('ABC-123 · Original sample');
  expect(displayTitle({code:'ABC-123',title:'Original sample',display_title:'   '})).toBe('ABC-123 · Original sample');
 });
 it('does not repeat an existing same code and always puts canonical code first',()=>{
  for(const title of ['ABC-123 · 合成标题','合成标题 ABC-123','abc_123 合成标题','【ABC-123】合成标题','ABC-123 · 合成标题 · ABC-123'])expect(displayTitle({code:'ABC-123',title})).toBe('ABC-123 · 合成标题');
  expect(displayTitle({code:'FC2-PPV-4961775',title:'FC2-PPV-4961775'})).toBe('FC2-PPV-4961775');
  expect(displayTitle({code:'ABC-123',title:'作品 ABC-1234'})).toBe('ABC-123 · 作品 ABC-1234');
 });
 it('keeps no-code fallback and raw inputs unchanged, including long titles',()=>{
  const item={title:'未识别的合成原标题',display_title:'合成中文',code:''};expect(displayTitle(item)).toBe('合成中文');expect(item.title).toBe('未识别的合成原标题');expect(item.display_title).toBe('合成中文');
  expect(displayTitle({title:'无号原文'})).toBe('无号原文');expect(displayTitle({code:'ABC-123',title:''})).toBe('ABC-123');
  const long='合成很长标题'.repeat(50);expect(displayTitle({code:'ABC-123',title:long})).toBe('ABC-123 · '+long);
 });
});

describe('category original label only',()=>{it('keeps internal canonical out of original hint and leaves actor/title unchanged',()=>{
 const category={name:'乳交',name_original:'パイズリ',display_name:'パイズリ',name_zh:null,name_translation:{state:'original',method:'original'}};
 expect(displayName(category)).toBe('パイズリ');expect(nameHint(category)).toBe('パイズリ');expect(nameHint(category)).not.toContain('乳交');
 expect(nameHint({name:'Original Actor',display_name:'演员中文',name_translation:{state:'canonical',method:'actor_alias'}})).toBe('演员中文 · 同一演员');
});});


describe('translation hints preserve original content without a missing-translation notice',()=>{
 it('returns no fallback label and no leading separator for unchanged original fields',()=>{
  for(const info of [undefined,{state:'original',method:'original'},{state:'unavailable',method:'none'}]){
   const item={title:'原片名 sample',display_title:'保留显示片名',name:'原名称',display_name:'保留显示名称',title_translation:info,name_translation:info};const before=JSON.stringify(item);
   expect(translationLabel(info)).toBe('');expect(titleHint(item)).toBe('原标题：原片名 sample');expect(nameHint(item)).toBe('原名：原名称');expect(displayTitle(item)).toBe('保留显示片名');expect(displayName(item)).toBe('保留显示名称');expect(JSON.stringify(item)).toBe(before);
  }
 });
 it.each([['machine','机翻，非官方中文'],['dictionary','中文释义'],['normalized_unverified','简体规范，原语言未确认']])('keeps the %s status label and original-field hints',(method,label)=>{
  const info={state:'unchanged',method};expect(translationLabel(info)).toBe(label);expect(titleHint({title:'原片名',title_translation:info})).toBe(`${label} · 原标题：原片名`);expect(nameHint({name:'原名称',name_translation:info})).toBe(`${label} · 原名：原名称`);
 });
 it('retains name_original precedence over actor alias and original-name branches',()=>{
  expect(nameHint({name:'canonical',name_original:'原始名称',display_name:'显示名',name_translation:{state:'alias',method:'actor_alias'}})).toBe('原始名称');
  expect(nameHint({name:'canonical',name_original:'',name_translation:{state:'original',method:'actor_original'}})).toBe('');
  expect(nameHint({name:'原演员',display_name:'演员别名',name_translation:{state:'alias',method:'actor_alias'}})).toBe('演员别名 · 同一演员');
  expect(nameHint({name:'原演员',display_name:'显示名',name_translation:{state:'original',method:'actor_original'}})).toBe('原演员');
 });
});
