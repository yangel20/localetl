/**
 * Client-side mirror of the config-scalar rules (B) in docs/architecture.md section 5
 * "Value casting" (decision Q6-3). Advisory only: the server (`POST /pipelines/validate`) is authoritative.
 * All digit classes are ASCII; JS `[0-9]` is used on purpose.
 */
import type { ColumnType } from '../../app/api/types';

const INT_RE = /^[+-]?[0-9]+$/;
const FLOAT_RE = /^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$/;
const DATE_RE = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/;
const DATETIME_RE =
  /^([0-9]{4})-([0-9]{2})-([0-9]{2})[T ]([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.[0-9]{1,6})?)?$/;
const BIGINT_MIN = -(2n ** 63n);
const BIGINT_MAX = 2n ** 63n - 1n;

export type ScalarValue = string | number | boolean;

export function isIntegerText(s: string): boolean {
  if (!INT_RE.test(s)) return false;
  const n = BigInt(s);
  return n >= BIGINT_MIN && n <= BIGINT_MAX;
}
export function isFloatText(s: string): boolean {
  return FLOAT_RE.test(s) && Number.isFinite(Number(s));
}
export function isBooleanText(s: string): boolean {
  return ['true', 'false', 'yes', 'no', '1', '0'].includes(s.toLowerCase());
}
export function isIsoDate(s: string): boolean {
  const m = DATE_RE.exec(s);
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const dt = new Date(Date.UTC(y, mo - 1, d));
  return y >= 1 && dt.getUTCFullYear() === y && dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d;
}
export function isIsoDatetime(s: string): boolean {
  const m = DATETIME_RE.exec(s);
  if (!m) return false;
  return isIsoDate(`${m[1]}-${m[2]}-${m[3]}`) && Number(m[4]) < 24 && Number(m[5]) < 60 && Number(m[6] ?? 0) < 60;
}

/** True when a JSON config scalar is acceptable for a column of `type` (rule set B). */
export function isCastableConfigScalar(value: unknown, type: ColumnType): boolean {
  switch (type) {
    case 'string':
      return typeof value === 'string'; // C-c
    case 'integer':
      if (typeof value === 'boolean') return false;
      if (typeof value === 'number') {
        return Number.isInteger(value) && value >= -(2 ** 63) && value <= 2 ** 63 - 1;
      }
      return typeof value === 'string' && isIntegerText(value.trim());
    case 'float':
      if (typeof value === 'boolean') return false;
      if (typeof value === 'number') return Number.isFinite(value);
      return typeof value === 'string' && isFloatText(value.trim());
    case 'boolean':
      if (typeof value === 'boolean') return true;
      if (typeof value === 'number') return value === 0 || value === 1;
      return typeof value === 'string' && isBooleanText(value.trim());
    case 'date': // C-b: always ISO, never the column format
      return typeof value === 'string' && isIsoDate(value);
    case 'datetime':
      return typeof value === 'string' && isIsoDatetime(value);
  }
}

export type ParsedScalar = { ok: true; value: ScalarValue } | { ok: false; message: string };

/** Turns text typed in the UI into the JSON scalar the config needs for a column type. */
export function parseScalarInput(text: string, type: ColumnType): ParsedScalar {
  const bad = (what: string): ParsedScalar => ({ ok: false, message: `Enter ${what}.` });
  const t = text.trim();
  switch (type) {
    case 'string':
      return { ok: true, value: text }; // never stripped
    case 'integer':
      return isIntegerText(t) ? { ok: true, value: Number(t) } : bad('a whole number');
    case 'float':
      return isFloatText(t) ? { ok: true, value: Number(t) } : bad('a number');
    case 'boolean': {
      if (!isBooleanText(t)) return bad('true, false, yes, no, 1 or 0');
      return { ok: true, value: ['true', 'yes', '1'].includes(t.toLowerCase()) };
    }
    case 'date':
      return isIsoDate(t) ? { ok: true, value: t } : bad('an ISO date (YYYY-MM-DD)');
    case 'datetime':
      return isIsoDatetime(t) ? { ok: true, value: t } : bad('an ISO datetime (YYYY-MM-DDTHH:MM[:SS[.ffffff]])');
  }
}

const TIME_DIRECTIVES = new Set(['H', 'I', 'M', 'S', 'f', 'p', 'X', 'c']);
const ZONE_DIRECTIVES = new Set(['z', 'Z']);

/** Directive letters used in a strptime format; `%%` is an escaped percent sign. */
export function formatDirectives(format: string): string[] {
  const out: string[] = [];
  for (let i = 0; i < format.length; i++) {
    if (format[i] !== '%') continue;
    const next = format[i + 1];
    if (next === undefined) break;
    if (next !== '%') out.push(next);
    i++;
  }
  return out;
}

/** Rule 7 / decision C-e. Returns a message, or null when the format is acceptable for the type. */
export function checkFormat(format: string, type: ColumnType): string | null {
  if (type !== 'date' && type !== 'datetime') {
    return 'format is allowed only on date and datetime columns';
  }
  if (format.length < 2 || format.length > 64) return 'format must be 2 to 64 characters';
  const dirs = formatDirectives(format);
  if (dirs.some((d) => ZONE_DIRECTIVES.has(d))) return 'format may not contain zone directives (%z, %Z)';
  if (type === 'date' && dirs.some((d) => TIME_DIRECTIVES.has(d))) {
    return 'a date format may not contain time directives (%H %I %M %S %f %p %X %c)';
  }
  return null;
}
