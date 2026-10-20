import { describe, expect, it } from 'vitest';
import {
  checkFormat,
  compareBounds,
  normalizeIso,
  formatDirectives,
  isCastableConfigScalar as ok,
  parseScalarInput,
} from './casting';

describe('config scalar casting (rule set B)', () => {
  it('integer', () => {
    expect(ok(5, 'integer')).toBe(true);
    expect(ok(1.0, 'integer')).toBe(true); // JSON cannot tell 1.0 from 1
    expect(ok('42', 'integer')).toBe(true);
    expect(ok(' +007 ', 'integer')).toBe(true);
    expect(ok(1.5, 'integer')).toBe(false);
    expect(ok(true, 'integer')).toBe(false);
    expect(ok('1_000', 'integer')).toBe(false);
    expect(ok('1,000', 'integer')).toBe(false);
    expect(ok('١٢', 'integer')).toBe(false); // non-ASCII digits
    expect(ok('9223372036854775807', 'integer')).toBe(true);
    expect(ok('9223372036854775808', 'integer')).toBe(false);
    expect(ok('1e3', 'integer')).toBe(false);
  });
  it('float', () => {
    expect(ok(1.5, 'float')).toBe(true);
    expect(ok('.5', 'float')).toBe(true);
    expect(ok('1e3', 'float')).toBe(true);
    expect(ok('1.', 'float')).toBe(true);
    expect(ok(true, 'float')).toBe(false);
    expect(ok('nan', 'float')).toBe(false);
    expect(ok('inf', 'float')).toBe(false);
    expect(ok('1e400', 'float')).toBe(false);
    expect(ok('1,5', 'float')).toBe(false);
    expect(ok('1_0.5', 'float')).toBe(false);
    expect(ok(Infinity, 'float')).toBe(false);
  });
  it('boolean', () => {
    for (const v of [true, false, 0, 1, 'TRUE', 'no', 'Yes', '0']) expect(ok(v, 'boolean')).toBe(true);
    for (const v of [2, 't', 'y', 'on', '2']) expect(ok(v, 'boolean')).toBe(false);
  });
  it('date and datetime are ISO only (C-b)', () => {
    expect(ok('2026-10-20', 'date')).toBe(true);
    for (const v of ['20261020', '2026-W43-2', '2026-10-20T00:00', '2026-02-30', 20261020]) {
      expect(ok(v, 'date')).toBe(false);
    }
    expect(ok('2026-10-20T10:00', 'datetime')).toBe(true);
    expect(ok('2026-10-20 10:00:30.123456', 'datetime')).toBe(true);
    for (const v of ['2026-10-20T10:00Z', '2026-10-20T10:00+02:00', '20261020T1000', '2026-10-20', '2026-10-20T25:00']) {
      expect(ok(v, 'datetime')).toBe(false);
    }
  });
  it('string accepts only JSON strings (C-c)', () => {
    expect(ok('abc', 'string')).toBe(true);
    expect(ok('', 'string')).toBe(true);
    expect(ok(5, 'string')).toBe(false);
    expect(ok(true, 'string')).toBe(false);
  });
});

describe('parseScalarInput', () => {
  it('produces the right JSON type per column type', () => {
    expect(parseScalarInput('42', 'integer')).toEqual({ ok: true, value: 42 });
    expect(parseScalarInput('1.5', 'float')).toEqual({ ok: true, value: 1.5 });
    expect(parseScalarInput('Yes', 'boolean')).toEqual({ ok: true, value: true });
    expect(parseScalarInput('0', 'boolean')).toEqual({ ok: true, value: false });
    expect(parseScalarInput(' keep ', 'string')).toEqual({ ok: true, value: ' keep ' });
    expect(parseScalarInput('2026-10-20', 'date')).toEqual({ ok: true, value: '2026-10-20' });
  });
  it('explains bad input', () => {
    expect(parseScalarInput('1.5', 'integer')).toMatchObject({ ok: false });
    expect(parseScalarInput('20261020', 'date')).toMatchObject({ ok: false });
  });
});

describe('format directives (rule 7, C-e)', () => {
  it('extracts directives and ignores %%', () => {
    expect(formatDirectives('%Y-%m-%d')).toEqual(['Y', 'm', 'd']);
    expect(formatDirectives('100%% %H')).toEqual(['H']);
  });
  it('allowed only on date/datetime', () => {
    expect(checkFormat('%Y-%m-%d', 'integer')).toMatch(/only on date and datetime/);
    expect(checkFormat('%Y-%m-%d', 'string')).not.toBeNull();
  });
  it('date: no time or zone directives', () => {
    expect(checkFormat('%d/%m/%Y', 'date')).toBeNull();
    for (const d of 'HIMSfpXc') expect(checkFormat(`%Y-%m-%${d}`, 'date')).toMatch(/time directives/);
    expect(checkFormat('%Y-%m-%d%z', 'date')).toMatch(/zone/);
  });
  it('datetime: time allowed, zone not', () => {
    expect(checkFormat('%Y-%m-%d %H:%M:%S', 'datetime')).toBeNull();
    expect(checkFormat('%Y-%m-%d %H:%M %Z', 'datetime')).toMatch(/zone/);
  });
  it('length 2 to 64', () => {
    expect(checkFormat('%', 'date')).toMatch(/2 to 64/);
    expect(checkFormat('%Y'.repeat(33), 'date')).toMatch(/2 to 64/);
  });
});

describe('integer precision', () => {
  it('keeps exact digits instead of rounding through Number', () => {
    expect(parseScalarInput('9007199254740991', 'integer')).toEqual({ ok: true, value: 9007199254740991 });
    expect(parseScalarInput('9007199254740992', 'integer')).toEqual({ ok: true, value: '9007199254740992' });
    expect(parseScalarInput('9007199254740993', 'integer')).toEqual({ ok: true, value: '9007199254740993' });
    expect(parseScalarInput('-9007199254740993', 'integer')).toEqual({ ok: true, value: '-9007199254740993' });
    expect(parseScalarInput(' 42 ', 'integer')).toEqual({ ok: true, value: 42 });
  });
  it('applies the bigint bound with BigInt', () => {
    expect(parseScalarInput('9223372036854775807', 'integer')).toEqual({ ok: true, value: '9223372036854775807' });
    expect(parseScalarInput('-9223372036854775808', 'integer')).toEqual({ ok: true, value: '-9223372036854775808' });
    expect(parseScalarInput('9223372036854775808', 'integer')).toMatchObject({ ok: false });
    expect(parseScalarInput('-9223372036854775809', 'integer')).toMatchObject({ ok: false });
  });
  it('flags 2**63 as a JSON number and accepts the digit string for the largest value', () => {
    expect(ok(2 ** 63, 'integer')).toBe(false);
    expect(ok(-(2 ** 63), 'integer')).toBe(true);
    expect(ok('9223372036854775807', 'integer')).toBe(true);
    expect(ok('9223372036854775808', 'integer')).toBe(false);
  });
});

describe('bound comparison by value', () => {
  it('normalises separators, seconds and fractions', () => {
    expect(normalizeIso('2026-01-01 10:00')).toBe('2026-01-01T10:00:00.000000');
    expect(normalizeIso('2026-01-01T10:00:00')).toBe('2026-01-01T10:00:00.000000');
    expect(normalizeIso('2026-01-01T10:00:00.5')).toBe('2026-01-01T10:00:00.500000');
    expect(normalizeIso('2026-01-01')).toBe('2026-01-01');
  });
  it('datetime: T versus space, both orderings, and equal values written differently', () => {
    expect(compareBounds('2026-01-01T10:00', '2026-01-01 11:00', 'datetime')).toBeLessThan(0);
    expect(compareBounds('2026-01-01 11:00', '2026-01-01T10:00', 'datetime')).toBeGreaterThan(0);
    expect(compareBounds('2026-01-01 10:00', '2026-01-01T10:00:00.000', 'datetime')).toBe(0);
    expect(compareBounds('2026-01-01T10:00:00.5', '2026-01-01 10:00:00.25', 'datetime')).toBeGreaterThan(0);
  });
  it('date and numeric bounds', () => {
    expect(compareBounds('2026-01-01', '2026-12-31', 'date')).toBeLessThan(0);
    expect(compareBounds('2026-12-31', '2026-01-01', 'date')).toBeGreaterThan(0);
    expect(compareBounds(2, 10, 'float')).toBeLessThan(0);
    expect(compareBounds(2, 10, 'integer')).toBeLessThan(0);
    expect(compareBounds('9007199254740993', '9007199254740992', 'integer')).toBeGreaterThan(0);
    expect(compareBounds('9007199254740993', 9007199254740992, 'integer')).toBeGreaterThan(0);
  });
});
