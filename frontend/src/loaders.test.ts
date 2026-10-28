import { afterEach, describe, expect, it, vi } from "vitest";
import type { LoaderFunctionArgs } from "react-router";
import { loadDirectory, loadVideoList } from "./loaders";
import { readResult } from "./data";
const id = (n: number) => n.toString(16).padStart(24, "0");
const args = (
  url: string,
  params: Record<string, string> = {},
): LoaderFunctionArgs =>
  ({
    request: new Request("https://example.invalid" + url),
    params,
    context: {},
  }) as LoaderFunctionArgs;
afterEach(() => vi.unstubAllGlobals());

describe("page loader behavior", () => {
  it("keeps implicit entity and every existing filter, sort and page parameter", async () => {
    const fetcher = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) =>
        Response.json({ items: [] }),
    );
    vi.stubGlobal("fetch", fetcher);
    const call = args(
      `/actors/${id(1)}?category=${id(2)}&studio=${id(3)}&q=番号&sort=oldest&page=2`,
      { id: id(1) },
    );
    await loadVideoList(call, "actors");
    expect(fetcher).toHaveBeenCalledTimes(2);
    const u = new URL(String(fetcher.mock.calls[0][0]), "https://example.invalid");
    expect(Object.fromEntries(u.searchParams)).toEqual({
      actor: id(1),
      category: id(2),
      studio: id(3),
      q: "番号",
      sort: "oldest",
      page: "2",
    });
    expect(fetcher.mock.calls[1][0]).toBe("/api/entities/actors/" + id(1));
    expect(fetcher.mock.calls[0][1]).toEqual({ signal: call.request.signal });
  });
  it("does not add entity or facet requests to the home list", async () => {
    const fetcher = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) =>
        Response.json({ items: [] }),
    );
    vi.stubGlobal("fetch", fetcher);
    await loadVideoList(args("/?q=片名&sort=duration"));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toBe(
      "/api/videos?q=%E7%89%87%E5%90%8D&sort=duration",
    );
  });
  it.each([390, 760, 761, 1024, 1100, 1101, 1440])("uses category/studio grid size on the first request at width %i and keeps search/page", async (width) => {
    vi.stubGlobal("window", { matchMedia: (q: string) => ({ matches: width <= Number(q.match(/\d+/)![0]) }) });
    const fetcher = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) =>
        Response.json({ items: [] }),
    );
    vi.stubGlobal("fetch", fetcher);
    for (const kind of ["categories", "studios"] as const) {
    fetcher.mockClear();
    const result = await loadDirectory(args("/" + kind + "?q=主観&page=2"), kind);
    expect(result.pageSize).toBe(width > 1100 ? 64 : 60);
    const u = new URL(String(fetcher.mock.calls[0][0]), "https://example.invalid");
    expect(u.pathname).toBe("/api/entities/" + kind);
    expect(Object.fromEntries(u.searchParams)).toEqual({
      q: "主観",
      page: "2",
      limit: width > 1100 ? "64" : "60",
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    }
  });
  it.each(["actors"] as const)("keeps %s exactly 60 without reading the viewport", async (kind) => {
    const fetcher = vi.fn(async (_url: RequestInfo | URL) => Response.json({ items: [] }));
    vi.stubGlobal("fetch", fetcher);
    const result = await loadDirectory(args("/" + kind + "?q=name&page=2"), kind);
    expect(fetcher.mock.calls[0][0]).toBe("/api/entities/" + kind + "?q=name&page=2&limit=60");
    expect(result).toEqual({ data: { items: [] } });
  });
  it.each(["categories", "studios"] as const)("passes %s abort through, including cancellation during fetch", async (kind) => {
    vi.stubGlobal("window", { matchMedia: () => ({ matches: false }) });
    const call = args("/" + kind + "?page=2");
    const error = new DOMException("Superseded", "AbortError");
    const controller = new AbortController();
    call.request = new Request(call.request, { signal: controller.signal });
    vi.stubGlobal("fetch", vi.fn((_url, init) => new Promise((_resolve, reject) => {
      expect(init.signal).toBe(call.request.signal);
      init.signal.addEventListener("abort", () => reject(error));
    })));
    const result = loadDirectory(call, kind);
    controller.abort();
    await expect(result).rejects.toBe(error);
  });
  it.each([6, 4, 3, 2])("keeps video pages 36 for %i columns without viewport or extra limit", async (columns) => {
    expect(36 % columns).toBe(0);
    vi.stubGlobal("window", { matchMedia: () => { throw Error("video loaders must not read viewport"); } });
    for (const kind of [undefined, "actors", "categories", "studios"] as const) {
      const fetcher = vi.fn(async (_url: RequestInfo | URL) => Response.json({ items: [], total: 100, page: 1, pages: 3 }));
      vi.stubGlobal("fetch", fetcher);
      const result = await loadVideoList(args(kind ? "/" + kind + "/" + id(1) : "/?q=name", kind ? { id: id(1) } : {}), kind);
      expect(fetcher).toHaveBeenCalledTimes(kind ? 2 : 1);
      expect(new URL(String(fetcher.mock.calls[0][0]), "https://example.invalid").searchParams.has("limit")).toBe(false);
      expect(Object.keys(result.list)).toEqual(["data"]);
    }
    for (const actorColumns of [6, 5, 3]) expect(60 % actorColumns).toBe(0);
  });
  it("returns the same visible error policy for a failed page and lets retries refetch", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 429 }))
      .mockResolvedValueOnce(Response.json({ items: [] }));
    vi.stubGlobal("fetch", fetcher);
    expect((await loadDirectory(args("/actors"), "actors")).error).toBe(
      "当前读取请求较多，请稍后重试",
    );
    expect((await loadDirectory(args("/actors"), "actors")).data).toEqual({
      items: [],
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("does not turn a cancelled/superseded navigation into a visible error", async () => {
    const control = new AbortController();
    control.abort();
    const cancelled = new DOMException("Cancelled", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(cancelled));
    await expect(readResult("/api/videos", control.signal)).rejects.toBe(
      cancelled,
    );
  });
});
