import { describe, expect, it } from 'vitest';
import { formatCell, nextSort, nullPercent, pageRange, toNullSplit, toTopValuePoints } from './format';

describe('explorer formatting', () => {
  it('renders cells as text', () => {
    expect(formatCell(null)).toBe('∅');
    expect(formatCell(true)).toBe('true');
    expect(formatCell(7)).toBe('7');
    expect(formatCell(0.1 + 0.2)).toBe('0.3');
    expect(formatCell('<b>x</b>')).toBe('<b>x</b>');
  });
  it('cycles single-column sort', () => {
    const a = nextSort(null, 'x');
    expect(a).toEqual({ column: 'x', order: 'asc' });
    expect(nextSort(a, 'x')).toEqual({ column: 'x', order: 'desc' });
    expect(nextSort({ column: 'x', order: 'desc' }, 'x').order).toBe('asc');
    expect(nextSort(a, 'y')).toEqual({ column: 'y', order: 'asc' });
  });
  it('computes page ranges', () => {
    expect(pageRange(0, 25, 0)).toEqual({ from: 0, to: 0, hasPrev: false, hasNext: false });
    expect(pageRange(60, 25, 25)).toEqual({ from: 26, to: 50, hasPrev: true, hasNext: true });
    expect(pageRange(60, 25, 50)).toEqual({ from: 51, to: 60, hasPrev: true, hasNext: false });
  });
  it('profiles: null percent, top values, null split', () => {
    expect(nullPercent(1, 3)).toBe('33%');
    expect(nullPercent(0, 0)).toBe('0%');
    expect(toTopValuePoints({ top_values: [{ value: null, count: 2 }, { value: 'a', count: 1 }] })).toEqual([
      { label: '∅', count: 2 }, { label: 'a', count: 1 },
    ]);
    expect(toNullSplit({ null_count: 5 }, 3)).toEqual([{ name: 'Non-null', count: 0 }, { name: 'Null', count: 3 }]);
  });
});
