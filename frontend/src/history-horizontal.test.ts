import {describe,it,expect,vi,beforeEach} from 'vitest';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {MemoryRouter} from 'react-router';
import {History,type HistoryRow} from './History';
import type {Video} from './types';
// @ts-expect-error Node is provided by Vitest, not the browser tsconfig.
import {readFileSync} from 'node:fs';
const state=vi.hoisted(()=>({data:undefined as unknown,loading:false,error:''}));
vi.mock('./hooks',()=>({useData:()=>({...state,retry:vi.fn()}),useScroll:()=>undefined}));
vi.mock('./auth-client',()=>({currentSession:()=>({id:23}),writeJson:vi.fn()}));
const video={id:'v',channel_id:123,message_id:201,title:'OLD-FILENAME.mp4',display_title:'TEST-201 · 長い作品タイトル 中文标题完整保留',code:'TEST-201',cover:'/api/videos/123/201/cover',duration:600,entities:{actors:[],categories:[],studios:[]}} as unknown as Video;
const row:HistoryRow={id:'row1',work_id:'work1',title:'PERSISTED-FILENAME.mp4',video,part_number:2,position:42,duration:600,completed:true,updated_at:1793152800000,available:true,note:'原分段保留说明',channel_id:123,message_id:201};
const render=()=>renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:['/history?page=2']},createElement(History)));
beforeEach(()=>{state.loading=false;state.error='';state.data={items:[row],page:2,pages:3,total:7}});
describe('horizontal account history cards',()=>{
 it('uses independent cover/content/metadata links and keeps delete inside the right info column',()=>{
  const html=render(),card=html.match(/<article[\s\S]*?<\/article>/)?.[0]||'';
  expect(card).toContain('class="history-art"');
  expect(card).toContain('<div class="history-info"><a class="history-content"');
  expect(card).toContain('<div class="history-meta"><a class="history-details"');
  expect(card).toContain('</a><div class="history-delete"><button');
  expect(card.match(/href="\/watch\/123\/201\?resume=row1"/g)).toHaveLength(3);
  for(const link of card.match(/<a\b[\s\S]*?<\/a>/g)||[])expect(link).not.toContain('<button');
 });
 it('retains full title, pink-code hook, part/progress/date/note/completed and accessible delete name',()=>{
  const html=render();
  for(const text of ['watch-code','TEST-201','長い作品タイトル 中文标题完整保留','第2段','0:42 / 10:00','已看完',new Date(row.updated_at).toLocaleString('zh-CN'),'原分段保留说明','删除历史：TEST-201 · 長い作品タイトル 中文标题完整保留'])expect(html).toContain(text);
  expect(html).not.toContain('FILENAME.mp4');
 });
 it('keeps unavailable entries honest, disabled, complete and deletable',()=>{
  state.data={items:[{...row,available:false,video:null,part_number:null,note:'作品当前不可用，历史仍可删除'}],page:2,pages:3,total:7};
  const html=render();expect(html.match(/aria-disabled="true"/g)).toHaveLength(3);
  for(const text of ['作品资料当前不可用','当前不可用','第—段','作品当前不可用，历史仍可删除','删除历史：作品资料当前不可用'])expect(html).toContain(text);
  expect(html).not.toContain('PERSISTED-FILENAME');
 });
 it('preserves clear confirmation entry and filtered pagination',()=>{
  const html=render();expect(html).toContain('清空历史');expect(html).toContain('rel="prev" href="/history"');expect(html).toContain('/history?page=3');
 });
 it('preserves loading, error/retry and empty presentations',()=>{
  state.loading=true;expect(render()).toContain('正在读取视频');
  state.loading=false;state.error='隔离测试错误';expect(render()).toContain('历史未取得');expect(render()).toContain('重试');
  state.error='';state.data={items:[],page:1,pages:1,total:0};expect(render()).toContain('还没有播放历史');
 });
 it('keeps horizontal 200/120 artwork columns even below 360 and uses natural right-side confirmation flow',()=>{
  const css=readFileSync(new URL('./style.css',import.meta.url),'utf8');
  const history=css.slice(css.indexOf('.history-page {'));
  expect(history).toContain('grid-template-columns:200px minmax(0,1fr)');
  expect(history).toContain('grid-template-columns:120px minmax(0,1fr)');
  expect(history).toContain('.history-info { min-width:0; }');
  expect(history).toContain('.history-delete:has(p) { flex-basis:100%');
  expect(history).not.toMatch(/\.history-(?:delete|content|info)[^{}]*\{[^{}]*(?:position:absolute|grid-column:1\/-1)/);
  expect(history).not.toContain('.history-content { flex-direction:column; }');
  expect(history).not.toContain('text-overflow:ellipsis');
 });
});
