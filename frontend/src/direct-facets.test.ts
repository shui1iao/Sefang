import {describe,it,expect} from 'vitest';
import {facetItems} from './facet-model';
import {facetLink,hasSessionBack} from './navigation';
import {SORT_VALUES} from './sort-model';
const id=(n:number)=>n.toString(16).padStart(24,'0');
describe('direct facets',()=>{
 it.each(SORT_VALUES)('switches nonempty same-kind routes, preserves normalized combination and %s sort, drops stale query and page',(sort)=>{
  for(const [kind,key,other] of [['categories','category','studio'],['studios','studio','category'],['actors','actor','studio']] as const){
   const u=new URL(facetLink(`?${kind==='actors'?'category':'actor'}=${id(1)}&${key}=${id(9)}&${other}=${id(3)}&q=番号&sort=${sort}&page=4&bad=drop`,key,id(205),{kind,id:id(2)}),'http://local');
   expect(u.pathname).toBe(`/${kind}/${id(205)}`);expect(u.searchParams.has(key)).toBe(false);expect(u.searchParams.get(other)).toBe(id(3));expect(u.searchParams.get(kind==='actors'?'category':'actor')).toBe(id(1));expect(u.searchParams.get('q')).toBe('番号');expect(u.searchParams.get('sort')).toBe(sort==='newest'?null:sort);expect(u.searchParams.has('page')).toBe(false);expect(u.searchParams.has('bad')).toBe(false);
  }
 });
 it('retains studio clear semantics and only trusts indices beyond this document boot',()=>{
  const u=new URL(facetLink(`?category=${id(3)}&sort=oldest&page=3`,'studio','',{kind:'studios',id:id(2)}),'http://local');expect(u.pathname).toBe('/');expect(Object.fromEntries(u.searchParams)).toEqual({category:id(3),sort:'oldest'});
  expect(hasSessionBack({idx:4},2)).toBe(true);for(const state of [null,{}, {idx:'4'}, {idx:2}, {idx:1}, {idx:2.5}])expect(hasSessionBack(state,2)).toBe(false);
 });
 it('clears the implicit actor but retains other filters and query, and preserves cross-kind binding',()=>{
  const u=new URL(facetLink(`?actor=${id(9)}&category=${id(3)}&studio=${id(4)}&q=name&sort=oldest&page=3`,'actor','',{kind:'actors',id:id(2)}),'http://local');expect(u.pathname).toBe('/');expect(Object.fromEntries(u.searchParams)).toEqual({studio:id(4),category:id(3),q:'name',sort:'oldest'});
  const cross=new URL(facetLink('?q=name&page=3','actor',id(5),{kind:'categories',id:id(3)}),'http://local');expect(cross.pathname).toBe('/');expect(Object.fromEntries(cross.searchParams)).toEqual({actor:id(5),category:id(3),q:'name'});
 });
 it('matches reliable actor alias and original name without inventing translated identity',()=>{
  const actor={id:id(206),name:'Original Actor',display_name:'可靠中文别名',aliases:['可靠中文别名'],count:2};
  for(const query of ['Original Actor','可靠中文别名'])expect(facetItems([actor],query,'count').map(x=>x.id)).toEqual([id(206)]);
 });
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
