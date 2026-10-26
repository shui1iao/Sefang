import {describe,it,expect} from 'vitest';
import main from './main.tsx?raw';
import pickers from './pickers.tsx?raw';
// @ts-expect-error Node is provided by Vitest; browser tsconfig intentionally omits Node types.
import {readFileSync} from 'node:fs';
const css=readFileSync(new URL('./style.css',import.meta.url),'utf8');
describe('scoped compact UI contracts',()=>{
 it('mounts own facets in category/studio lists but none in actors, preserving clear',()=>{
  expect(main).toContain('{(kind||params.size>0)&&<div className="filters">{kind&&kind!==\'actors\'&&<>');
  expect(main).toContain('{kind!==\'studios\'&&<FacetStrip kind="categories"');
  expect(main).toContain('{kind!==\'categories\'&&<FacetStrip kind="studios"');
  expect(main).toContain('kind="categories"');expect(main).toContain('kind="studios"');
  expect(main).toContain('{params.size>0&&<Link className="clear" to="/">清除筛选</Link>}');
  expect(main).toContain("!kind&&!params.get('q')&&<ActorStrip");
 });
 it('retains cover detail helpers but hides all list and related cover details including actors',()=>{
  expect(main).toContain('function Artwork({video,showCoverDetails=true}');expect(main).toContain('function Card({video,showCoverDetails=true}');
  expect(main).toContain("{showCoverDetails&&<strong>{video.code||'未识别番号'}</strong>}<small>暂无封面</small>");
  expect(main).toContain('{showCoverDetails&&<span className="duration"');expect(main).toContain('{showCoverDetails&&video.code&&<span className="code-badge"');
  expect(main).toContain('data.data.items.map(v=><Card key={v.id} video={v} showCoverDetails={false}/>)');
  expect(main).toContain('related.data?.items.map(v=><Card key={v.id} video={v} showCoverDetails={false}/>)');expect(main).toContain('{displayTitle(video)}</h3>');
 });
 it('uses the same existing nonmodal anchored RadioGroup at all widths',()=>{
  for(const unused of ['Dialog','ResponsiveLayer','MobileSort','compact','matchMedia'])expect(pickers).not.toContain(unused);
  expect(pickers).toContain('<Menu.Root open={open} onOpenChange={setOpen} modal={false}>');expect(pickers).toContain('<Menu.RadioGroup value={value} onValueChange={choose}>');
  expect(pickers).toContain('collisionPadding={12} avoidCollisions loop');expect(pickers).toContain('restoreTrigger(event,triggerRef)');
  for(const unused of ['picker-sheet','picker-overlay','picker-slide','picker-sort-options'])expect(css).not.toContain(unused);
 });
 it('limits compact geometry to category and studio directories',()=>{
  expect(css).toContain('[data-directory="categories"] .entity-grid,[data-directory="studios"] .entity-grid{grid-template-columns:repeat(8,');
  expect(css).toContain('grid-template-columns:repeat(3,minmax(0,1fr));gap:8px');
  expect(css).toContain('.entity-grid.actors{grid-template-columns:repeat(6,minmax(0,1fr))}');
  expect(main).toContain('data-directory={kind}');expect(main).toContain('title={nameHint(e)}');
 });
});
