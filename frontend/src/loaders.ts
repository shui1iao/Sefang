import type { LoaderFunctionArgs } from "react-router";
import { filterKey, normalizeQuery, type Kind } from "./navigation";
import { readResult, type DataResult } from "./data";
import type { Entity, Page, Video } from "./types";

const DIRECTORY_PAGE = 60;
export type ListData = {
  list: DataResult<Page<Video>>;
  entity: DataResult<Entity>;
};

/** Router loaders keep the current page mounted until the next primary content is ready.
 * They use the existing endpoints and query semantics, without a second data cache.
 */
export async function loadVideoList(
  { request, params }: LoaderFunctionArgs,
  kind?: Kind,
): Promise<ListData> {
  const query = normalizeQuery(new URL(request.url).search);
  if (kind && params.id) query.set(filterKey(kind), params.id);
  const text = query.toString();
  const [list, entity] = await Promise.all([
    readResult<Page<Video>>(
      "/api/videos" + (text ? "?" + text : ""),
      request.signal,
    ),
    kind && params.id
      ? readResult<Entity>(`/api/entities/${kind}/${params.id}`, request.signal)
      : Promise.resolve({}),
  ]);
  return { list, entity };
}

export function loadDirectory(
  { request }: LoaderFunctionArgs,
  kind: Kind,
): Promise<DataResult<Page<Entity>>> {
  const query = normalizeQuery(new URL(request.url).search);
  query.set("limit", String(DIRECTORY_PAGE));
  return readResult<Page<Entity>>(
    `/api/entities/${kind}?${query}`,
    request.signal,
  );
}
