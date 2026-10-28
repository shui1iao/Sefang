import { describe, expect, it } from "vitest";
import { categoryAnchorPage, categoryColumns, categoryPageSize } from "./category-pagination";
// @ts-expect-error Node is provided by Vitest; browser tsconfig intentionally omits Node types.
import { readFileSync } from "node:fs";
const css = readFileSync(new URL("./style.css", import.meta.url), "utf8");
describe("category/studio shared adaptive directory pagination", () => {
  it.each([[390,3,60],[760,3,60],[761,6,60],[1024,6,60],[1100,6,60],[1101,8,64],[1440,8,64]])("derives width %i columns and whole rows", (width,columns,size) => {
    expect(categoryColumns(q => width <= Number(q.match(/\d+/)![0]))).toBe(columns);
    expect(categoryPageSize(columns)).toBe(size);
    expect(size % columns).toBe(0);
  });
  it("agrees with the unchanged CSS breakpoints/columns", () => {
    expect(css).toMatch(/\.entity-grid \{[^}]*repeat\(8,/);
    for (const [width,cols] of [[1100,6],[760,3]]) expect(css).toMatch(new RegExp("@media \\(max-width: "+width+"px\\)[\\s\\S]*?\\.entity-grid \\{[^}]*repeat\\("+cols+","));
  });
  it("keeps the previous first item on a valid page in both directions, including the old last page", () => {
    for (const [oldSize,size] of [[60,64],[64,60]]) {
      for (let page=1; page<=Math.ceil(308/oldSize); page++) {
        const mapped=categoryAnchorPage(page,oldSize,size,308),offset=(page-1)*oldSize;
        expect(mapped).toBeGreaterThanOrEqual(1);expect(mapped).toBeLessThanOrEqual(Math.ceil(308/size));
        expect((mapped-1)*size).toBeLessThanOrEqual(offset);expect(mapped*size).toBeGreaterThan(offset);
      }
    }
    expect(categoryAnchorPage(6,60,64,308)).toBe(5);
    expect(categoryAnchorPage(99,60,64,308)).toBe(5);
    expect(categoryAnchorPage(1,60,64,0)).toBe(1);
  });
});
