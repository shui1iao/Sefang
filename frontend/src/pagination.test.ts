import {describe,it,expect} from 'vitest';
import {jumpPage,pageHref} from './pagination';
describe('shared manual page navigation',()=>{
 it('accepts integer targets, normalizes full-width digits and clamps boundaries',()=>{
  expect(jumpPage('3',8)).toBe(3);expect(jumpPage('８',8)).toBe(8);expect(jumpPage(' ００２ ',8)).toBe(2);
  expect(jumpPage('999999999999999999999999',8)).toBe(8);expect(jumpPage('0',8)).toBe(1);expect(jumpPage('-2',8)).toBe(1);
 });
 it('does not navigate for empty, nonnumeric, decimal or invalid result counts',()=>{
  for(const value of ['',' ','abc','2.5','1e2','NaN','Infinity','2 3','--2'])expect(jumpPage(value,8)).toBeNull();
  for(const pages of [0,-1,1.5,NaN])expect(jumpPage('2',pages)).toBeNull();
 });
 it('keeps list filters and sort while the first page has no page parameter',()=>{
  const id='a'.repeat(24),search=`?actor=${id}&studio=${id}&category=${id}&q=test&sort=release&page=4`;
  expect(pageHref('/',search,3)).toBe(`/?actor=${id}&studio=${id}&category=${id}&q=test&sort=release&page=3`);
  expect(pageHref('/',search,1)).toBe(`/?actor=${id}&studio=${id}&category=${id}&q=test&sort=release`);
 });
 it('keeps a directory path and uses the existing query normalization',()=>{
  expect(pageHref('/categories','?q=test&page=4&series=bad&next=bad',2)).toBe('/categories?q=test&page=2');
 });
});
