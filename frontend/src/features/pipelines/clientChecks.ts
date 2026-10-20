/**
 * Client-side config checks: JSON Schema shape plus the architecture section 6 rules and the
 * section 5 "Value casting" scalar rules. They give fast feedback only; `POST /pipelines/validate`
 * is authoritative. Regex patterns are NOT compiled here (the server uses Python `re`).
 * Error paths are JSON Pointers relative to the config, e.g. `/transformations/2/columns`.
 */
import type { ErrorDetail } from '../../app/api/types';
import { checkFormat, compareBounds, isCastableConfigScalar, isIsoDate, isIsoDatetime } from './casting';
import { TRANSFORMATION_OPS, VALIDATION_RULES } from './configModel';

const IDENT_RE = /^[a-z_][a-z0-9_]{0,62}$/;
const TYPES = ['integer', 'float', 'boolean', 'date', 'datetime', 'string'] as const;
type ColType = (typeof TYPES)[number];
type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v);

export interface CheckOptions {
  /** CSV headers of the chosen data source; enables rule 8. */
  sourceColumns?: readonly string[];
}

/** Strips the request prefix so server paths (`/config/...`) and client paths line up. */
export function normalizeErrorPath(path: string): string {
  return path.replace(/^\/config(?=\/|$)/, '') || '/';
}

export function checkConfig(config: unknown, options: CheckOptions = {}): ErrorDetail[] {
  const errors: ErrorDetail[] = [];
  const err = (path: string, message: string) => errors.push({ path, message });

  if (!isObj(config)) {
    err('/', 'The config must be an object.');
    return errors;
  }
  const allowedTop = ['version', 'columns', 'transformations', 'validations', 'on_validation_failure', 'max_rejected_ratio', 'target'];
  for (const k of Object.keys(config)) if (!allowedTop.includes(k)) err(`/${k}`, 'Unknown property.');

  if (config.version !== 1) err('/version', 'version must be 1.');

  // --- columns (rules 1, 7, 8) ---
  const typeByName = new Map<string, ColType>();
  if (!Array.isArray(config.columns) || config.columns.length < 1 || config.columns.length > 500) {
    err('/columns', 'Provide between 1 and 500 columns.');
  } else {
    const names = new Set<string>();
    const sources = new Set<string>();
    config.columns.forEach((c, i) => {
      const p = `/columns/${i}`;
      if (!isObj(c)) return err(p, 'Each column must be an object.');
      for (const k of Object.keys(c)) {
        if (!['source', 'name', 'type', 'format', 'nullable'].includes(k)) err(`${p}/${k}`, 'Unknown property.');
      }
      const source = c.source;
      if (typeof source !== 'string' || source.length < 1 || source.length > 255) {
        err(`${p}/source`, 'source must be 1 to 255 characters.');
      } else {
        if (sources.has(source)) err(`${p}/source`, `Duplicate source column "${source}".`);
        sources.add(source);
        if (options.sourceColumns && !options.sourceColumns.includes(source)) {
          err(`${p}/source`, `"${source}" is not a column of the selected data source.`);
        }
      }
      const name = c.name;
      if (typeof name !== 'string' || !IDENT_RE.test(name)) {
        err(`${p}/name`, 'name must be lowercase letters, digits or underscores, starting with a letter or underscore (max 63).');
      } else {
        if (names.has(name)) err(`${p}/name`, `Duplicate column name "${name}".`);
        names.add(name);
      }
      const type = c.type;
      const validType = (TYPES as readonly unknown[]).includes(type);
      if (!validType) err(`${p}/type`, `type must be one of ${TYPES.join(', ')}.`);
      else if (typeof name === 'string') typeByName.set(name, type as ColType);
      if (c.nullable !== undefined && typeof c.nullable !== 'boolean') err(`${p}/nullable`, 'nullable must be true or false.');
      if (c.format !== undefined) {
        if (typeof c.format !== 'string') err(`${p}/format`, 'format must be text.');
        else if (validType) {
          const m = checkFormat(c.format, type as ColType);
          if (m) err(`${p}/format`, m);
        }
      }
    });
  }

  const ref = (path: string, name: unknown): ColType | undefined => {
    if (typeof name !== 'string' || !IDENT_RE.test(name)) {
      err(path, 'Choose a column.');
      return undefined;
    }
    const t = typeByName.get(name);
    if (!t) err(path, `"${name}" is not one of the mapped columns.`);
    return t;
  };
  const colList = (path: string, v: unknown, required = true): string[] => {
    if (v === undefined && !required) return [];
    if (!Array.isArray(v) || v.length < 1) {
      err(path, 'Choose at least one column.');
      return [];
    }
    if (new Set(v).size !== v.length) err(path, 'Columns must not repeat.');
    v.forEach((n, i) => ref(`${path}/${i}`, n));
    return v.filter((n): n is string => typeof n === 'string');
  };
  const onlyType = (path: string, t: ColType | undefined, allowed: ColType[], what: string) => {
    if (t && !allowed.includes(t)) err(path, `${what} applies only to ${allowed.join('/')} columns.`);
  };

  // --- transformations (rules 2, 3, 4, 5) ---
  if (config.transformations !== undefined) {
    if (!Array.isArray(config.transformations) || config.transformations.length > 100) {
      err('/transformations', 'At most 100 transformations.');
    } else {
      config.transformations.forEach((t, i) => {
        const p = `/transformations/${i}`;
        if (!isObj(t) || !(TRANSFORMATION_OPS as readonly unknown[]).includes(t.op)) {
          return err(`${p}/op`, `op must be one of ${TRANSFORMATION_OPS.join(', ')}.`);
        }
        const allowed: Record<string, string[]> = {
          trim_whitespace: ['op', 'columns'],
          change_case: ['op', 'columns', 'case'],
          replace_values: ['op', 'column', 'mapping'],
          fill_null: ['op', 'column', 'value'],
          drop_null_rows: ['op', 'columns', 'how'],
          deduplicate: ['op', 'columns'],
          round_number: ['op', 'column', 'decimals'],
        };
        for (const k of Object.keys(t)) if (!allowed[t.op as string]?.includes(k)) err(`${p}/${k}`, 'Unknown property.');
        switch (t.op) {
          case 'trim_whitespace':
          case 'change_case': {
            const cols = colList(`${p}/columns`, t.columns);
            cols.forEach((n, j) => onlyType(`${p}/columns/${j}`, typeByName.get(n), ['string'], t.op as string));
            if (t.op === 'change_case' && !['lower', 'upper', 'title'].includes(t.case as string)) {
              err(`${p}/case`, 'case must be lower, upper or title.');
            }
            break;
          }
          case 'replace_values': {
            ref(`${p}/column`, t.column);
            const m = t.mapping;
            if (!isObj(m) || Object.keys(m).length < 1 || Object.keys(m).length > 1000) {
              err(`${p}/mapping`, 'Provide 1 to 1000 replacements.');
            } else {
              for (const [k, v] of Object.entries(m)) {
                if (!(v === null || ['string', 'number', 'boolean'].includes(typeof v))) {
                  err(`${p}/mapping/${k}`, 'Replacement must be text, a number, true/false or null.');
                }
              }
            }
            break;
          }
          case 'fill_null': {
            const ty = ref(`${p}/column`, t.column);
            if (!['string', 'number', 'boolean'].includes(typeof t.value)) err(`${p}/value`, 'Provide a value.');
            else if (ty && !isCastableConfigScalar(t.value, ty)) {
              err(`${p}/value`, `The value cannot be used for a ${ty} column.`);
            }
            break;
          }
          case 'drop_null_rows':
            colList(`${p}/columns`, t.columns);
            if (t.how !== undefined && t.how !== 'any' && t.how !== 'all') err(`${p}/how`, 'how must be any or all.');
            break;
          case 'deduplicate':
            colList(`${p}/columns`, t.columns, false);
            break;
          case 'round_number': {
            onlyType(`${p}/column`, ref(`${p}/column`, t.column), ['float'], 'round_number');
            if (!isInt(t.decimals) || t.decimals < 0 || t.decimals > 10) err(`${p}/decimals`, 'decimals must be a whole number from 0 to 10.');
            break;
          }
        }
      });
    }
  }

  // --- validations (rules 2, 3, 4, 5) ---
  if (config.validations !== undefined) {
    if (!Array.isArray(config.validations) || config.validations.length > 200) {
      err('/validations', 'At most 200 validations.');
    } else {
      config.validations.forEach((v, i) => {
        const p = `/validations/${i}`;
        if (!isObj(v) || !(VALIDATION_RULES as readonly unknown[]).includes(v.rule)) {
          return err(`${p}/rule`, `rule must be one of ${VALIDATION_RULES.join(', ')}.`);
        }
        const allowed: Record<string, string[]> = {
          not_null: ['rule', 'column'],
          unique: ['rule', 'columns'],
          range: ['rule', 'column', 'min', 'max'],
          allowed_values: ['rule', 'column', 'values'],
          regex: ['rule', 'column', 'pattern'],
          length: ['rule', 'column', 'min', 'max'],
        };
        for (const k of Object.keys(v)) if (!allowed[v.rule as string]?.includes(k)) err(`${p}/${k}`, 'Unknown property.');
        switch (v.rule) {
          case 'not_null':
            ref(`${p}/column`, v.column);
            break;
          case 'unique':
            colList(`${p}/columns`, v.columns);
            break;
          case 'range': {
            const ty = ref(`${p}/column`, v.column);
            onlyType(`${p}/column`, ty, ['integer', 'float', 'date', 'datetime'], 'range');
            if (v.min === undefined && v.max === undefined) err(p, 'Set a minimum, a maximum or both.');
            const okBound = (b: unknown): boolean => {
              if (!ty) return true;
              if (ty === 'integer') return typeof b !== 'boolean' && isCastableConfigScalar(b, 'integer');
              if (ty === 'float') return typeof b === 'number' && Number.isFinite(b);
              if (ty === 'date') return typeof b === 'string' && isIsoDate(b);
              if (ty === 'datetime') return typeof b === 'string' && isIsoDatetime(b);
              return true;
            };
            for (const k of ['min', 'max'] as const) {
              if (v[k] !== undefined && !okBound(v[k])) {
                err(`${p}/${k}`, ty === 'date' || ty === 'datetime' ? `Use an ISO ${ty} string.` : ty === 'integer' ? 'Use a whole number.' : 'Use a number.');
              }
            }
            if (v.min !== undefined && v.max !== undefined && okBound(v.min) && okBound(v.max) && ty && compareBounds(v.min as number | string, v.max as number | string, ty) > 0) {
              err(`${p}/min`, 'The minimum must not exceed the maximum.');
            }
            break;
          }
          case 'allowed_values': {
            const ty = ref(`${p}/column`, v.column);
            if (!Array.isArray(v.values) || v.values.length < 1 || v.values.length > 1000) {
              err(`${p}/values`, 'Provide 1 to 1000 values.');
            } else {
              if (new Set(v.values).size !== v.values.length) err(`${p}/values`, 'Values must not repeat.');
              v.values.forEach((x, j) => {
                if (ty && !isCastableConfigScalar(x, ty)) err(`${p}/values/${j}`, `This value cannot be used for a ${ty} column.`);
              });
            }
            break;
          }
          case 'regex': {
            onlyType(`${p}/column`, ref(`${p}/column`, v.column), ['string'], 'regex');
            if (typeof v.pattern !== 'string' || v.pattern.length < 1 || v.pattern.length > 200) {
              err(`${p}/pattern`, 'The pattern must be 1 to 200 characters.');
            }
            break;
          }
          case 'length': {
            onlyType(`${p}/column`, ref(`${p}/column`, v.column), ['string'], 'length');
            if (v.min === undefined && v.max === undefined) err(p, 'Set a minimum, a maximum or both.');
            if (v.min !== undefined && (!isInt(v.min) || v.min < 0)) err(`${p}/min`, 'The minimum must be a whole number, 0 or more.');
            if (v.max !== undefined && (!isInt(v.max) || v.max < 1)) err(`${p}/max`, 'The maximum must be a whole number, 1 or more.');
            if (isInt(v.min) && isInt(v.max) && v.min > v.max) err(`${p}/min`, 'The minimum must not exceed the maximum.');
            break;
          }
        }
      });
    }
  }

  if (config.on_validation_failure !== undefined && config.on_validation_failure !== 'reject_row' && config.on_validation_failure !== 'fail_run') {
    err('/on_validation_failure', 'Must be reject_row or fail_run.');
  }
  const r = config.max_rejected_ratio;
  if (r !== undefined && (typeof r !== 'number' || !(r >= 0 && r <= 1))) {
    err('/max_rejected_ratio', 'Must be a number from 0 to 1.');
  }

  // --- target (rule 9) ---
  const target = config.target;
  if (!isObj(target)) {
    err('/target', 'A target is required.');
  } else {
    for (const k of Object.keys(target)) if (k !== 'table' && k !== 'mode') err(`/target/${k}`, 'Unknown property.');
    if (typeof target.table !== 'string' || !IDENT_RE.test(target.table)) {
      err('/target/table', 'Table name must be lowercase letters, digits or underscores, starting with a letter or underscore (max 63).');
    } else if (target.table.startsWith('run_')) {
      err('/target/table', 'Table names starting with "run_" are reserved.');
    }
    if (target.mode !== 'replace' && target.mode !== 'append') err('/target/mode', 'Mode must be replace or append.');
  }
  return errors;
}
