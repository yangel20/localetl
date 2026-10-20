import { describe, expect, it } from 'vitest';
import { checkConfig, normalizeErrorPath } from './clientChecks';

const files = import.meta.glob('../../../../contracts/examples/pipeline/*/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, unknown>;
const byKind = (kind: 'valid' | 'invalid') =>
  Object.entries(files).filter(([p]) => p.includes(`/${kind}/`));

const base = () => ({
  version: 1,
  columns: [
    { source: 'id', name: 'id', type: 'integer' },
    { source: 'email', name: 'email', type: 'string' },
    { source: 'when', name: 'when', type: 'date' },
    { source: 'amt', name: 'amt', type: 'float' },
  ],
  target: { table: 'out', mode: 'replace' },
});
const paths = (c: unknown, o = {}) => checkConfig(c, o).map((e) => e.path);

describe('contract examples', () => {
  it('finds the examples', () => {
    expect(byKind('valid').length).toBeGreaterThanOrEqual(3);
    expect(byKind('invalid').length).toBeGreaterThanOrEqual(8);
  });
  it.each(byKind('valid'))('accepts %s', (_p, cfg) => {
    expect(checkConfig(cfg)).toEqual([]);
  });
  // Every schema-level invalid example must be caught client-side.
  it.each(byKind('invalid'))('rejects %s', (_p, cfg) => {
    expect(checkConfig(cfg).length).toBeGreaterThan(0);
  });
  it('reports the failing JSON Pointer for specific examples', () => {
    const get = (name: string) => byKind('invalid').find(([p]) => p.endsWith(`${name}.json`))![1];
    expect(paths(get('wrong_version'))).toContain('/version');
    expect(paths(get('bad_column_type'))).toEqual(expect.arrayContaining([expect.stringMatching(/^\/columns\/\d+\/type$/)]));
    expect(paths(get('bad_target_identifier'))).toContain('/target/table');
    expect(paths(get('bad_load_mode'))).toContain('/target/mode');
    expect(paths(get('range_without_bounds'))).toContain('/validations/0');
    expect(paths(get('unknown_transformation'))).toEqual(expect.arrayContaining([expect.stringMatching(/^\/transformations\/\d+\/op$/)]));
    expect(paths(get('missing_columns'))).toContain('/columns');
    expect(paths(get('extra_property'))).toEqual(expect.arrayContaining([expect.stringMatching(/\//)]));
  });
});

describe('section 6 rules', () => {
  it('1: duplicate names and sources', () => {
    const c = base();
    c.columns.push({ source: 'id', name: 'id', type: 'string' });
    expect(paths(c)).toEqual(expect.arrayContaining(['/columns/4/source', '/columns/4/name']));
  });
  it('2: unknown column references', () => {
    const c = { ...base(), transformations: [{ op: 'fill_null', column: 'ghost', value: 1 }], validations: [{ rule: 'not_null', column: 'ghost' }] };
    expect(paths(c)).toEqual(['/transformations/0/column', '/validations/0/column']);
  });
  it('3: string-only operations', () => {
    const c = { ...base(), transformations: [{ op: 'trim_whitespace', columns: ['id'] }], validations: [{ rule: 'regex', column: 'id', pattern: 'x' }, { rule: 'length', column: 'amt', min: 1 }] };
    expect(paths(c)).toEqual(['/transformations/0/columns/0', '/validations/0/column', '/validations/1/column']);
  });
  it('4: round_number float only; range types and order', () => {
    const c = {
      ...base(),
      transformations: [{ op: 'round_number', column: 'id', decimals: 2 }],
      validations: [
        { rule: 'range', column: 'email', min: 1 },
        { rule: 'range', column: 'amt', min: 5, max: 1 },
        { rule: 'range', column: 'when', min: '2026-02-30' },
        { rule: 'range', column: 'when', min: '2026-01-01', max: '2026-12-31' },
      ],
    };
    expect(paths(c)).toEqual(['/transformations/0/column', '/validations/0/column', '/validations/1/min', '/validations/2/min']);
  });
  it('5: castable fill_null and allowed_values; integer bounds integral', () => {
    const c = {
      ...base(),
      transformations: [{ op: 'fill_null', column: 'id', value: 'abc' }, { op: 'fill_null', column: 'email', value: 5 }],
      validations: [
        { rule: 'allowed_values', column: 'when', values: ['2026-10-20', '20261020'] },
        { rule: 'range', column: 'id', min: 1.5 },
      ],
    };
    expect(paths(c)).toEqual(['/transformations/0/value', '/transformations/1/value', '/validations/0/values/1', '/validations/1/min']);
  });
  it('7: format only on date/datetime, no time/zone directives for date', () => {
    const c = base();
    Object.assign(c.columns[0]!, { format: '%Y' });
    Object.assign(c.columns[2]!, { format: '%Y-%m-%d %H' });
    expect(paths(c)).toEqual(['/columns/0/format', '/columns/2/format']);
    Object.assign(c.columns[0]!, { format: undefined });
    Object.assign(c.columns[2]!, { format: '%d/%m/%Y' });
    expect(paths(c)).toEqual([]);
  });
  it('8: source columns', () => {
    expect(paths(base(), { sourceColumns: ['id', 'email', 'when'] })).toEqual(['/columns/3/source']);
  });
  it('9: reserved run_ prefix', () => {
    const c = { ...base(), target: { table: 'run_x', mode: 'append' } };
    expect(paths(c)).toEqual(['/target/table']);
  });
  it('ratio, list and decimals bounds', () => {
    const c = {
      ...base(),
      max_rejected_ratio: 1.5,
      transformations: [{ op: 'round_number', column: 'amt', decimals: 11 }, { op: 'trim_whitespace', columns: [] }, { op: 'replace_values', column: 'email', mapping: {} }],
    };
    expect(paths(c)).toEqual(['/transformations/0/decimals', '/transformations/1/columns', '/transformations/2/mapping', '/max_rejected_ratio']);
  });
});

describe('range bounds are compared by value', () => {
  const rangeOn = (column: string, min: unknown, max: unknown) => ({ ...base(), validations: [{ rule: 'range', column, min, max }] });
  const dt = () => ({ ...base(), columns: [{ source: 'ts', name: 'ts', type: 'datetime' }] });
  const withRange = (min: string, max: string) => ({ ...dt(), validations: [{ rule: 'range', column: 'ts', min, max }] });

  it('datetime: T and space separators order correctly', () => {
    expect(paths(withRange('2026-01-01T10:00', '2026-01-01 11:00'))).toEqual([]); // was a false positive
    expect(paths(withRange('2026-01-01 11:00', '2026-01-01T10:00'))).toEqual(['/validations/0/min']); // was a false pass
  });
  it('datetime: equal values written differently are accepted', () => {
    expect(paths(withRange('2026-01-01 10:00', '2026-01-01T10:00:00.000'))).toEqual([]);
  });
  it('date and numbers still order correctly', () => {
    expect(paths(rangeOn('when', '2026-01-01', '2026-12-31'))).toEqual([]);
    expect(paths(rangeOn('when', '2026-12-31', '2026-01-01'))).toEqual(['/validations/0/min']);
    expect(paths(rangeOn('amt', 2, 10))).toEqual([]);
    expect(paths(rangeOn('id', 10, 2))).toEqual(['/validations/0/min']);
  });
  it('large integer bounds as digit strings are accepted and compared exactly', () => {
    expect(paths(rangeOn('id', '9007199254740992', '9007199254740993'))).toEqual([]);
    expect(paths(rangeOn('id', '9007199254740993', '9007199254740992'))).toEqual(['/validations/0/min']);
    expect(paths(rangeOn('id', 0, '9223372036854775808'))).toEqual(['/validations/0/max']);
    expect(paths(rangeOn('id', 0, 2 ** 63))).toEqual(['/validations/0/max']);
  });
});

describe('normalizeErrorPath', () => {
  it('strips the request prefix', () => {
    expect(normalizeErrorPath('/config/columns/0/name')).toBe('/columns/0/name');
    expect(normalizeErrorPath('/columns/0/name')).toBe('/columns/0/name');
    expect(normalizeErrorPath('/config')).toBe('/');
    expect(normalizeErrorPath('/configuration/x')).toBe('/configuration/x');
  });
});
