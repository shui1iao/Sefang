import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { VideoGrid, Pages } from "./components";
import { FacetStrip } from "./pickers";
import type { Video } from "./types";
import mainSource from "./main.tsx?raw";
import components from "./components.tsx?raw";
import pickers from "./pickers.tsx?raw";
// @ts-expect-error Node is provided by Vitest; browser tsconfig intentionally omits Node types.
import { readFileSync } from "node:fs";
const css = readFileSync(new URL("./style.css", import.meta.url), "utf8");
const compact = (source: string) => source.replace(/\s/g, "").replaceAll('"', "'");
const main = compact(mainSource);
const render = (element: React.ReactNode) =>
  renderToStaticMarkup(
    createElement(
      MemoryRouter,
      { initialEntries: ["/actors/abc?sort=oldest&page=2"] },
      element,
    ),
  );
const video = {
  id: "one",
  channel_id: 42,
  message_id: 7,
  title: "ABC-123 原标题",
  code: "ABC-123",
  duration: 3600,
  cover: "/api/videos/42/7/cover",
  state: "matched",
  release_date: "2026-10-25",
  entities: {
    actors: [{ id: "actor", name: "演员原名" }],
    categories: [],
    studios: [],
  },
} as unknown as Video;

describe("shared UI contracts", () => {
  it("renders pure artwork by default, preserving the title and card metadata", () => {
    const html = render(createElement(VideoGrid, { items: [video] }));
    const artwork = html.match(/<div class="art">(.*?)<\/div>/)?.[1];
    expect(artwork).toContain('loading="lazy"');
    expect(artwork).not.toContain(video.code);
    expect(artwork).not.toContain("<span");
    expect(html).toContain("ABC-123 原标题");
    expect(html).toContain("演员原名");
    expect(html).toContain("2026-10-25");
    expect(html).toContain("/watch/42/7");
    for (const old of [
      "showCoverDetails",
      "code-badge",
      "cardDuration",
      "data-card-duration",
    ])
      expect(components + mainSource + css).not.toContain(old);
    expect(components).toContain("暂无封面");
    expect(components).toContain("thumbnail?skip_cover=true");
  });
  it("keeps list and related cards on the same renderer", () => {
    expect(main).toContain("<VideoGriditems={data.data.items}/>");
    expect(main).toContain("<VideoGriditems={related.data?.items??[]}/>");
  });
  it("preserves filtered pagination links and hides unnecessary paging", () => {
    const html = render(createElement(Pages, { page: 2, pages: 5 }));
    expect(html).toContain("/actors/abc?sort=oldest");
    expect(html).toContain("sort=oldest&amp;page=3");
    expect(html).toContain('aria-label="跳转页码"');
    expect(render(createElement(Pages, { page: 1, pages: 1 }))).toBe("");
  });
  it("mounts one keyed own-kind facet on all entity pages, with no home/search extra facets", () => {
    expect(main).toContain("kind&&(<divclassName='filters'><FacetStripkey={kind}kind={kind}value={params.get(filterKey(kind))||''}");
    expect(main).toContain("kind&&(<navclassName='back-row'>");
    expect(main).not.toContain("清除筛选");
    expect(pickers).not.toContain("LinkToDirectory");
    expect(pickers + css).not.toContain("facet-selection");
    expect(pickers).toContain("selectedId===entity.id");
    expect(pickers).toContain("selectedButton");
    expect(css).not.toContain(".clear");
    expect(css).not.toContain(".facet-label a");
    expect(main).toMatch(/!kind&&!params.get\('q'\)&&\(?<ActorStrip/);
  });
  it("renders all three facet types without selected/clear rows, preserving all and controls", () => {
    for (const [kind,label] of [["actors","演员"],["categories","分类"],["studios","发行商"]] as const) {
      const html=render(createElement(FacetStrip,{kind,value:"a".repeat(24),onChange:()=>{}}));
      expect(html).toContain('data-facet="'+kind+'"');
      for(const text of ["选择"+label,"全部"+label,"搜索"+label+"名称","展开全部"+label]) expect(html).toContain(text);
      for(const old of ["已选：","清除"+label,"data-facet-selection","重试名称"]) expect(html).not.toContain(old);
    }
  });
  it("keeps one nonmodal anchored sorting menu, no sheet or overlay", () => {
    expect(pickers).toContain("modal={false}");
    expect(pickers).toContain("<Menu.RadioGroup");
    for (const old of [
      "picker-sheet",
      "picker-overlay",
      "ResponsiveLayer",
      "MobileSort",
    ])
      expect(pickers + css).not.toContain(old);
  });
  it("keeps dense directory grids and removes styles for retired UI", () => {
    expect(compact(css)).toContain("grid-template-columns:repeat(8,minmax(0,1fr))");
    expect(compact(css)).toContain(
      ".entity-grid.actors{grid-template-columns:repeat(6,minmax(0,1fr))",
    );
    for (const old of [
      "footer",
      "related-reason",
      "watch-kicker",
      "code-badge",
      ".duration",
    ])
      expect(css).not.toContain(old);
    expect(main).toContain("data-directory={kind}");
  });
});
