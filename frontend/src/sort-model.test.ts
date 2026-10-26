import {describe,it,expect} from 'vitest';
import {SORT_FIELDS,SORT_VALUES,decodeSort,encodeSort} from './sort-model';
import {normalizeQuery,listLink} from './navigation';

describe('six sorting combinations',()=>{
 it('offers exactly three fields and two directions with a reversible encoding',()=>{
  expect(SORT_FIELDS.map(x=>x[1])).toEqual(['加入时间','时长','发行日期']);
  const values=[];
  for(const [field] of SORT_FIELDS)for(const direction of ['asc','desc'] as const){
   const value=encodeSort(field,direction);values.push(value);
   expect(decodeSort(value)).toEqual({field,direction});
  }
  expect(new Set(values)).toEqual(new Set(SORT_VALUES));
  expect(decodeSort('newest')).toEqual({field:'joined',direction:'desc'});
 });
 it('preserves all six modes in normalized links and resets page only on changed controls',()=>{
  const id='a'.repeat(24);
  for(const value of SORT_VALUES){
   const search=`?actor=${id}&studio=${id}&category=${id}&q=番号&sort=${value}&page=2`;
   const p=normalizeQuery(search);
   expect(p.get('sort')||'newest').toBe(value);
   expect(p.get('page')).toBe('2');
   const changed=new URL(listLink({sort:value},search),'https://example.invalid');
   expect(changed.searchParams.get('sort')||'newest').toBe(value);
   expect(changed.searchParams.has('page')).toBe(false);
   expect(changed.searchParams.get('actor')).toBe(id);
  }
 });
 it('removes the retired name choice and rejects unknown sort values',()=>{
  for(const value of ['name','popular','duration_desc','SQL'])expect(normalizeQuery('?sort='+value).has('sort')).toBe(false);
 });
});
