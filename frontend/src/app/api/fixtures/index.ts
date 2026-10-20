/** Typed fixtures for endpoints the backend does not serve yet. Types come from the generated contract. */
import type {
  CsvPreview,
  DataSource,
  Dataset,
  DatasetProfile,
  DatasetRowPage,
  Health,
  MetricsSummary,
  Pipeline,
  RejectedRowPage,
  Run,
  RunEvent,
} from '../types';

export const IDS = {
  source: '11111111-1111-4111-8111-111111111111',
  pipeline: '22222222-2222-4222-8222-222222222222',
  runSucceeded: '33333333-3333-4333-8333-333333333333',
  runRunning: '44444444-4444-4444-8444-444444444444',
  dataset: '55555555-5555-4555-8555-555555555555',
} as const;

export const health: Health = { status: 'ok', database: 'ok' };

export const source: DataSource = {
  id: IDS.source,
  name: 'orders',
  original_filename: 'orders.csv',
  size_bytes: 1024,
  csv_options: { encoding: 'utf-8', delimiter: ',', has_header: true, quote_char: '"' },
  columns: [
    { name: 'order_id', inferred_type: 'integer', null_count: 0 },
    { name: 'customer', inferred_type: 'string', null_count: 1 },
    { name: 'amount', inferred_type: 'float', null_count: 0 },
  ],
  row_count: 5,
  created_at: '2026-10-19T10:00:00Z',
};

export const preview: CsvPreview = {
  source_id: IDS.source,
  columns: source.columns,
  rows: [
    { order_id: '1', customer: 'Ada', amount: '19.99' },
    { order_id: '2', customer: null, amount: '5.00' },
  ],
  sampled_rows: 2,
};

export const pipeline: Pipeline = {
  id: IDS.pipeline,
  name: 'Orders cleanup',
  description: null,
  source_id: IDS.source,
  config: {
    version: 1,
    columns: [
      { source: 'order_id', name: 'order_id', type: 'integer', nullable: false },
      { source: 'customer', name: 'customer', type: 'string', nullable: true },
      { source: 'amount', name: 'amount', type: 'float', nullable: false },
    ],
    transformations: [{ op: 'trim_whitespace', columns: ['customer'] }],
    validations: [{ rule: 'not_null', column: 'order_id' }],
    on_validation_failure: 'reject_row',
    max_rejected_ratio: 0.1,
    target: { table: 'orders_clean', mode: 'replace' },
  },
  config_version: 1,
  created_at: '2026-10-19T10:05:00Z',
  updated_at: '2026-10-19T10:05:00Z',
  last_run: {
    id: IDS.runSucceeded,
    status: 'succeeded',
    queued_at: '2026-10-19T10:10:00Z',
    finished_at: '2026-10-19T10:10:02Z',
  },
};

/** Accounting holds: 5 extracted = 3 loaded + 1 rejected + 1 duplicate + 0 null dropped. */
export const runSucceeded: Run = {
  id: IDS.runSucceeded,
  pipeline_id: IDS.pipeline,
  pipeline_name: 'Orders cleanup',
  source_id: IDS.source,
  status: 'succeeded',
  current_stage: null,
  config_version: 1,
  queued_at: '2026-10-19T10:10:00Z',
  started_at: '2026-10-19T10:10:00Z',
  finished_at: '2026-10-19T10:10:02Z',
  duration_ms: 2000,
  extracted_count: 5,
  loaded_count: 3,
  rejected_count: 1,
  duplicate_dropped_count: 1,
  null_dropped_count: 0,
  dataset_id: IDS.dataset,
  error_message: null,
};

export const runRunning: Run = {
  ...runSucceeded,
  id: IDS.runRunning,
  status: 'running',
  current_stage: 'transform',
  finished_at: null,
  duration_ms: null,
  extracted_count: 5,
  loaded_count: 0,
  rejected_count: 1,
  duplicate_dropped_count: 0,
  null_dropped_count: 0,
  dataset_id: null,
};

export const runEvents: RunEvent[] = (
  [
    ['extract', 'started', null, null],
    ['extract', 'completed', 5, 5],
    ['transform', 'completed', 5, 4],
    ['validate', 'completed', 4, 3],
    ['load', 'completed', 3, 3],
    ['publish', 'completed', 3, 3],
  ] as const
).map(([stage, status, rows_in, rows_out], i) => ({
  id: i + 1,
  run_id: IDS.runSucceeded,
  stage,
  status,
  rows_in,
  rows_out,
  message: null,
  created_at: `2026-10-19T10:10:0${i}Z`,
}));

export const rejections: RejectedRowPage = {
  total: 1,
  limit: 50,
  offset: 0,
  items: [
    { row_number: 4, column: 'amount', rule: 'type_cast', message: 'not a float', value: 'abc' },
  ],
};

export const dataset: Dataset = {
  id: IDS.dataset,
  table_name: 'orders_clean',
  pipeline_id: IDS.pipeline,
  last_run_id: IDS.runSucceeded,
  row_count: 3,
  columns: [
    { name: 'order_id', type: 'integer' },
    { name: 'customer', type: 'string' },
    { name: 'amount', type: 'float' },
  ],
  published_at: '2026-10-19T10:10:02Z',
};

export const datasetRows: DatasetRowPage = {
  total: 3,
  limit: 50,
  offset: 0,
  columns: dataset.columns,
  items: [
    { order_id: 1, customer: 'Ada', amount: 19.99 },
    { order_id: 2, customer: null, amount: 5 },
    { order_id: 3, customer: 'Grace', amount: 7.5 },
  ],
};

export const datasetProfile: DatasetProfile = {
  dataset_id: IDS.dataset,
  row_count: 3,
  columns: [
    { name: 'order_id', type: 'integer', null_count: 0, distinct_count: 3, min: 1, max: 3, top_values: [{ value: 1, count: 1 }] },
    { name: 'customer', type: 'string', null_count: 1, distinct_count: 2, min: null, max: null, top_values: [{ value: 'Ada', count: 1 }] },
  ],
};

export const metricsSummary: MetricsSummary = {
  total_runs: 2,
  runs_by_status: { queued: 0, running: 1, succeeded: 1, failed: 0, interrupted: 0 },
  loaded_count_total: 3,
  avg_duration_ms: 2000,
  daily: [{ date: '2026-10-19', succeeded: 1, failed: 0, interrupted: 0, loaded_count: 3 }],
};
