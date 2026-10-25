import {describe,it,expect} from 'vitest';
import {normalizeQuery,safeLink,validWatch,listLink,segmentState} from './navigation';
describe('independent navigation contract',()=>{
 it('drops retired series query from links without changing other filters',()=>{const id='a'.repeat(24);expect(normalizeQuery('?series='+id+'&category='+id+'&page=2').toString()).toBe('category='+id+'&page=2');expect(listLink({studio:id},'?series='+id+'&sort=name&page=2')).toBe('/?studio='+id+'&sort=name')});
 it('normalizes bounded query and real sorting only',()=>{const p=normalizeQuery('?q='+encodeURIComponent('x'.repeat(400))+'&page=-1&sort=popular&actor=bad&next=https://bad.example');expect(p.get('q')?.length).toBe(300);expect(p.has('page')).toBe(false);expect(p.has('sort')).toBe(false);expect(p.has('next')).toBe(false);expect(p.has('actor')).toBe(false)});
 it('keeps filters while resetting page',()=>{expect(listLink({actor:'a'.repeat(24)},'?page=4&sort=release')).toBe('/?actor='+ 'a'.repeat(24)+'&sort=release')});
 it('blocks dangerous external links and invalid media ids',()=>{for(const url of ['javascript:alert(1)','file:///etc/passwd','https://user:pass@example.com','http://127.0.0.1'])expect(safeLink(url)).toBeNull();expect(safeLink('https://t.me/c/123/1')).toBeTruthy();expect(validWatch('123','1')).toBe(true);expect(validWatch('0','-1')).toBe(false);expect(validWatch('1','9007199254740992')).toBe(false)});
 it('segment replace keeps only the original list origin',()=>{expect(segmentState({from:'/?page=2&sort=release',other:'x'})).toEqual({from:'/?page=2&sort=release',segment:true});expect(segmentState(null)).toEqual({segment:true});expect(segmentState({from:42})).toEqual({segment:true})});
});
