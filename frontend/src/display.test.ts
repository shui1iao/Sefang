import {describe,it,expect} from 'vitest';
import {displayTitle,displayName,nameHint} from './display';
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
