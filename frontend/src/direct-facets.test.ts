import {describe,it,expect} from 'vitest';
import {facetItems} from './facet-model';
import {facetLink} from './navigation';
const id=(n:number)=>n.toString(16).padStart(24,'0');
describe('direct facets',()=>{
 it('searches translated and original names across more than one metadata page',()=>{
 const all=Array.from({length:205},(_,n)=>({id:id(n+1),name:'Original '+n,name_zh:n===204?'中文分类':'标签'+n,count:205-n}));
 expect(facetItems(all,'中文分类','count').map(x=>x.id)).toEqual([id(205)]);
 expect(facetItems(all,'original 204','count')[0].id).toBe(id(205));
 });
 it('changes one field, preserves actor/q/sort and drops page',()=>{
 const u=new URL(facetLink(`?actor=${id(1)}&category=${id(2)}&studio=${id(3)}&q=番号&sort=duration&page=4`,'category',id(205)),'http://local');
 expect(u.pathname).toBe('/');expect(Object.fromEntries(u.searchParams)).toEqual({actor:id(1),category:id(205),studio:id(3),q:'番号',sort:'duration'});
 });
 it('clears an implicit category on its detail route instead of rebinding it',()=>{
 const u=new URL(facetLink(`?studio=${id(3)}&page=3`,'category','',{kind:'categories',id:id(2)}),'http://local');
 expect(u.pathname).toBe('/');expect(Object.fromEntries(u.searchParams)).toEqual({studio:id(3)});
 });
 it('keeps implicit actor or studio when changing the other field',()=>{
 expect(new URL(facetLink('?q=x','category',id(4),{kind:'actors',id:id(1)}),'http://local').searchParams.get('actor')).toBe(id(1));
 expect(new URL(facetLink('','category',id(4),{kind:'studios',id:id(3)}),'http://local').searchParams.get('studio')).toBe(id(3));
 });
});
