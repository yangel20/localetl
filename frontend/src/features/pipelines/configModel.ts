import type {
  ColumnInfo,
  ColumnMapping,
  DataSource,
  PipelineConfig,
  Transformation,
  Validation,
} from '../../app/api/types';

export const TRANSFORMATION_OPS = [
  'trim_whitespace',
  'change_case',
  'replace_values',
  'fill_null',
  'drop_null_rows',
  'deduplicate',
  'round_number',
] as const satisfies readonly Transformation['op'][];

export const VALIDATION_RULES = [
  'not_null',
  'unique',
  'range',
  'allowed_values',
  'regex',
  'length',
] as const satisfies readonly Validation['rule'][];

export const OP_LABEL: Record<(typeof TRANSFORMATION_OPS)[number], string> = {
  trim_whitespace: 'Trim whitespace',
  change_case: 'Change case',
  replace_values: 'Replace values',
  fill_null: 'Fill empty values',
  drop_null_rows: 'Drop rows with empty values',
  deduplicate: 'Remove duplicate rows',
  round_number: 'Round numbers',
};
export const RULE_LABEL: Record<(typeof VALIDATION_RULES)[number], string> = {
  not_null: 'Not empty',
  unique: 'Unique',
  range: 'Range',
  allowed_values: 'Allowed values',
  regex: 'Matches pattern',
  length: 'Text length',
};

const IDENT_MAX = 63;

/** Lower-snake identifier derived from a CSV header; the user can edit it. */
export function suggestIdentifier(header: string, taken: ReadonlySet<string> = new Set()): string {
  let base = header
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '');
  if (!base || !/^[a-z_]/.test(base)) base = `col_${base}`.replace(/_+$/, '') || 'col';
  base = base.slice(0, IDENT_MAX - 4);
  let name = base;
  for (let i = 2; taken.has(name); i++) name = `${base}_${i}`;
  return name;
}

const INFERRED_TO_TYPE = (c: ColumnInfo): ColumnMapping['type'] => c.inferred_type;

/** One mapping per source column, in file order, with inferred types. */
export function columnsFromSource(source: Pick<DataSource, 'columns'>): ColumnMapping[] {
  const taken = new Set<string>();
  return source.columns.map((c) => {
    const name = suggestIdentifier(c.name, taken);
    taken.add(name);
    return { source: c.name, name, type: INFERRED_TO_TYPE(c), nullable: true };
  });
}

export function emptyConfig(columns: ColumnMapping[] = [], table = ''): PipelineConfig {
  return {
    version: 1,
    columns,
    transformations: [],
    validations: [],
    on_validation_failure: 'reject_row',
    max_rejected_ratio: 1,
    target: { table, mode: 'replace' },
  };
}

export function newTransformation(op: Transformation['op'], firstColumn: string): Transformation {
  switch (op) {
    case 'trim_whitespace':
      return { op, columns: [firstColumn] };
    case 'change_case':
      return { op, columns: [firstColumn], case: 'lower' };
    case 'replace_values':
      return { op, column: firstColumn, mapping: {} };
    case 'fill_null':
      return { op, column: firstColumn, value: '' };
    case 'drop_null_rows':
      return { op, columns: [firstColumn], how: 'any' };
    case 'deduplicate':
      return { op };
    case 'round_number':
      return { op, column: firstColumn, decimals: 2 };
  }
}

export function newValidation(rule: Validation['rule'], firstColumn: string): Validation {
  switch (rule) {
    case 'not_null':
      return { rule, column: firstColumn };
    case 'unique':
      return { rule, columns: [firstColumn] };
    case 'range':
      return { rule, column: firstColumn };
    case 'allowed_values':
      return { rule, column: firstColumn, values: [] };
    case 'regex':
      return { rule, column: firstColumn, pattern: '' };
    case 'length':
      return { rule, column: firstColumn };
  }
}

/** Returns a new array with the item at `from` moved to `to` (no-op when out of range). */
export function moveItem<T>(items: readonly T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) return [...items];
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item as T);
  return next;
}
