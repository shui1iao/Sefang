import {describe,it,expect} from 'vitest';
import {facetItems,isComposing,moveOption} from './facet-model';
const rows=[{id:'c',name:'中文分类',count:2},{id:'a',name:'あいう 日本語',count:9},{id:'b',name:'ＡＢＣ 标题',count:5}];
describe('facet selection model',()=>{
 it('defaults to real count descending without mutating input',()=>{expect(facetItems(rows,'','count').map(e=>e.count)).toEqual([9,5,2]);expect(rows[0].id).toBe('c')});
 it('searches Chinese/Japanese and normalized width/case',()=>{expect(facetItems(rows,'中文','count')[0].id).toBe('c');expect(facetItems(rows,'日本語','count')[0].id).toBe('a');expect(facetItems(rows,'abc','count')[0].id).toBe('b');expect(facetItems(rows,'不存在','count')).toEqual([])});
 it('sorts by name with stable id tie breaking',()=>{const result=facetItems([...rows,{id:'z',name:'中文分类',count:20}],'','name');expect(result.map(e=>e.name)).toEqual(result.map(e=>e.name).sort((a,b)=>a.localeCompare(b,'ja')));expect(result.filter(e=>e.name==='中文分类').map(e=>e.id)).toEqual(['c','z'])});
 it('supports arrow wrapping and Home/End; ignores nonnavigation',()=>{expect(moveOption('ArrowDown',2,3)).toBe(0);expect(moveOption('ArrowUp',0,3)).toBe(2);expect(moveOption('Home',1,3)).toBe(0);expect(moveOption('End',1,3)).toBe(2);expect(moveOption('a',0,3)).toBe(null);expect(moveOption('ArrowDown',0,0)).toBe(null)});
 it('does not select during IME composition including legacy 229',()=>{expect(isComposing({isComposing:true})).toBe(true);expect(isComposing({keyCode:229})).toBe(true);expect(isComposing({isComposing:false})).toBe(false)});
 it('searches reviewed category aliases without changing ids or counts',()=>{const x=[{id:'canonical',name:'乳交',count:52,aliases:['パイズリ','他妈的奶']}];expect(facetItems(x,'パイズリ','count')).toEqual(x);expect(facetItems(x,'他妈的奶','count')).toEqual(x);expect(facetItems(x,'unknown','count')).toEqual([])});
});
