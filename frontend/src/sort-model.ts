export const SORT_FIELDS = [
  ['joined', '加入时间'],
  ['duration', '时长'],
  ['release', '发行日期'],
] as const;
export type SortField = typeof SORT_FIELDS[number][0];
export type SortDirection = 'asc' | 'desc';
export const SORT_VALUES = ['newest', 'oldest', 'duration', 'duration_asc', 'release', 'release_asc'] as const;

export function decodeSort(value: string): {field: SortField; direction: SortDirection} {
  const direction = value === 'oldest' || value.endsWith('_asc') ? 'asc' : 'desc';
  const field = value.startsWith('duration') ? 'duration' : value.startsWith('release') ? 'release' : 'joined';
  return {field, direction};
}
export function encodeSort(field: SortField, direction: SortDirection): string {
  if (field === 'joined') return direction === 'asc' ? 'oldest' : 'newest';
  return field + (direction === 'asc' ? '_asc' : '');
}
