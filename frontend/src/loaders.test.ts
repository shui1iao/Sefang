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
  it("preserves the 60-item directory page and search query", async () => {
    const fetcher = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) =>
        Response.json({ items: [] }),
    );
    vi.stubGlobal("fetch", fetcher);
    await loadDirectory(args("/categories?q=主観&page=2"), "categories");
    const u = new URL(String(fetcher.mock.calls[0][0]), "https://example.invalid");
    expect(u.pathname).toBe("/api/entities/categories");
    expect(Object.fromEntries(u.searchParams)).toEqual({
      q: "主観",
      page: "2",
      limit: "60",
    });
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
