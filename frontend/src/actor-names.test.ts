import {describe,it,expect} from 'vitest';
import {displayName,nameHint,translationLabel} from './display';
describe('confirmed actor name display only',()=>{
 it('shows both verified names with an accurate non-machine hint',()=>{
  const actor={name:'天使もえ',name_zh:'天使萌',display_name:'天使もえ / 天使萌',name_translation:{state:'verified_alias',method:'actor_alias'}};
  expect(displayName(actor)).toBe('天使もえ / 天使萌');expect(nameHint(actor)).toBe('天使もえ / 天使萌 · 同一演员');expect(nameHint(actor)).not.toContain('机翻');expect(nameHint(actor)).not.toContain('暂无');
 });
 it('keeps fallback and other category translation behavior',()=>{
  const actor={name:'小野夕子',display_name:'小野夕子',name_translation:{state:'original',method:'actor_original'}};
  expect(displayName(actor)).toBe('小野夕子');expect(nameHint(actor)).toBe('小野夕子');expect(nameHint({name:'category',name_translation:{state:'translated',method:'dictionary'}})).toBe('中文释义 · 原名：category');expect(translationLabel({state:'translated',method:'machine'})).toBe('机翻，非官方中文');
 });
});
