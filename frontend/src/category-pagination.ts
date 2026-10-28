import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router";
import { pageHref } from "./pagination";
import { normalizeQuery, type Kind } from "./navigation";
import type { Entity, Page } from "./types";

// Keep these two existing category/studio grid breakpoints aligned with style.css.
export const CATEGORY_BREAKPOINTS = ["(max-width: 1100px)", "(max-width: 760px)"] as const;
export function categoryColumns(matches: (query: string) => boolean): number {
  return matches(CATEGORY_BREAKPOINTS[1]) ? 3 : matches(CATEGORY_BREAKPOINTS[0]) ? 6 : 8;
}
export function categoryPageSize(columns: number): number {
  return Math.ceil(60 / columns) * columns;
}
export function currentCategoryPageSize(): number {
  return categoryPageSize(categoryColumns(query => window.matchMedia(query).matches));
}
export function categoryAnchorPage(page: number, oldSize: number, size: number, total: number): number {
  return Math.min(Math.max(1, Math.ceil(total / size)), Math.floor((page - 1) * oldSize / size) + 1);
}

/** Only category and studio directories subscribe. Router navigation owns cancellation and result commit. */
export function useCategoryPagination(kind: Kind, result: { pageSize?: number; data?: Page<Entity> }, pendingLocation: () => { pathname: string; search: string } | undefined) {
  const loc = useLocation(), navigate = useNavigate();
  useEffect(() => {
    if (kind === "actors" || !result.pageSize) return;
    let requestedSize = result.pageSize;
    const update = () => {
      const pending = pendingLocation();
      if (pending) {
        if (pending.pathname !== loc.pathname) return;
        const before = normalizeQuery(loc.search), next = normalizeQuery(pending.search);
        before.delete("page"); next.delete("page");
        // Let a different in-flight search/filter commit before aligning its own first item.
        if (before.toString() !== next.toString()) return;
      }
      const size = currentCategoryPageSize();
      if (size === requestedSize) return;
      requestedSize = size;
      const page = categoryAnchorPage(result.data?.page || 1, result.pageSize!, size, result.data?.total || 0);
      // Replace keeps resize out of the back chain; even same-URL navigation cancels an older size.
      void navigate(pageHref(loc.pathname, loc.search, page), { replace: true });
    };
    // 6 and 3 columns both divide 60: their boundary needs no fetch.
    const media = window.matchMedia(CATEGORY_BREAKPOINTS[0]);
    media.addEventListener("change", update);
    update(); // Also covers a breakpoint crossed while the initial loader was still pending.
    return () => media.removeEventListener("change", update);
  }, [kind, result, loc.pathname, loc.search, navigate, pendingLocation]);
}
