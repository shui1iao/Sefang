import { requireLogin } from "./auth-client";
export type DataResult<T> = { data?: T; error?: string };

/** The same response policy is used by page loaders and asynchronous side panels. */
export async function readJson<T>(
  url: string,
  signal: AbortSignal,
): Promise<T> {
  const response = await fetch(url, { signal });
  if (response.status === 401) requireLogin();
  if (!response.ok) {
    throw Error(
      response.status === 404
        ? "内容未取得或不在当前视频库"
        : response.status === 429
          ? "当前读取请求较多，请稍后重试"
          : "请求未完成，请重试",
    );
  }
  return response.json();
}

export async function readResult<T>(
  url: string,
  signal: AbortSignal,
): Promise<DataResult<T>> {
  try {
    return { data: await readJson<T>(url, signal) };
  } catch (error) {
    // A superseded navigation must not commit its result or error to the next page.
    if (signal.aborted) throw error;
    return {
      error: error instanceof Error ? error.message : "请求未完成，请重试",
    };
  }
}
