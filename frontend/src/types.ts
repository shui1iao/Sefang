import type { Kind } from "./navigation";
import type { Group } from "./segments";
import type { Named, Titled } from "./display";

export type Entity = Named & {
  id: string;
  kind: Kind;
  name: string;
  count: number;
  avatar: string | null;
  avatar_state: string;
};
export type Video = Titled & {
  id: string;
  channel_id: number;
  message_id: number;
  title: string;
  code: string;
  duration: number | null;
  part_count?: number;
  duration_complete?: boolean;
  group?: Group;
  width: number;
  height: number;
  size: number;
  mime: string;
  available: boolean;
  uploaded_at: string;
  release_date: string | null;
  state: string;
  cover: string;
  has_cover: boolean;
  entities: Record<Kind, (Named & { id: string })[]>;
  original_name?: string;
  caption?: string;
  protected?: boolean;
  checked_at?: number;
  sources?: { name: string; url: string | null }[];
  message_url?: string;
  stream?: string;
  related_reason?: string;
};
export type Page<T> = {
  items: T[];
  total: number;
  page: number;
  pages: number;
};
