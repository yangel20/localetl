import type { components } from './schema';

type S = components['schemas'];

/**
 * Pipeline config as clients write and read it.
 *
 * openapi-typescript marks every field that has a JSON Schema `default` as required and
 * exposes the schema's `$defs` block as a property. Neither matches the wire format
 * (`contracts/pipeline.schema.json` allows omitting defaulted fields and has no `$defs` value),
 * so those are relaxed here. The server remains authoritative (`POST /pipelines/validate`).
 */
type GeneratedConfig = S['PipelineConfig'];
type Defaulted = 'transformations' | 'validations' | 'on_validation_failure' | 'max_rejected_ratio';
export type ColumnMapping = Omit<S['PipelineConfig']['$defs']['ColumnMapping'], 'nullable'> & {
  nullable?: boolean;
};
export type PipelineConfig = Omit<GeneratedConfig, '$defs' | Defaulted | 'columns'> & {
  columns: ColumnMapping[];
  transformations?: Transformation[];
  validations?: Validation[];
} & Partial<Pick<GeneratedConfig, 'on_validation_failure' | 'max_rejected_ratio'>>;

type Defs = S['PipelineConfig']['$defs'];
export type Transformation =
  | Defs['TrimWhitespace']
  | Defs['ChangeCase']
  | Defs['ReplaceValues']
  | Defs['FillNull']
  | Defs['DropNullRows']
  | Defs['Deduplicate']
  | Defs['RoundNumber'];
/**
 * openapi-typescript collapses `Range` and `Length` (JSON Schema `anyOf` of required-bounds)
 * to `unknown`, so their shapes are restated here from pipeline.schema.json.
 */
export type RangeValidation = {
  rule: 'range';
  column: string;
  min?: number | string;
  max?: number | string;
};
export type LengthValidation = { rule: 'length'; column: string; min?: number; max?: number };
export type Validation =
  | Defs['NotNull']
  | Defs['Unique']
  | Defs['AllowedValues']
  | Defs['Regex']
  | RangeValidation
  | LengthValidation;
export type ColumnType = S['ColumnType'];
export type CsvOptions = S['CsvOptions'];

export type ErrorCode = S['Error']['error']['code'];
export type ErrorDetail = S['ErrorDetail'];

export type Health = S['Health'];
export type ColumnInfo = S['ColumnInfo'];
export type DataSource = S['DataSource'];
export type DataSourcePage = S['DataSourcePage'];
export type CsvPreview = S['CsvPreview'];
export type SourceUploadOptions = Partial<
  Pick<S['SourceUpload'], 'name' | 'encoding' | 'delimiter' | 'has_header' | 'quote_char'>
>;

export type Pipeline = Omit<S['Pipeline'], 'config'> & { config: PipelineConfig };
export type PipelinePage = Omit<S['PipelinePage'], 'items'> & { items: Pipeline[] };
export type PipelineCreate = Omit<S['PipelineCreate'], 'config'> & { config: PipelineConfig };
export type PipelineValidationResult = S['PipelineValidationResult'];

export type RunStatus = S['RunStatus'];
export type Stage = S['Stage'];
export type Run = S['Run'];
export type RunPage = S['RunPage'];
export type RunEvent = S['RunEvent'];
export type RejectedRow = S['RejectedRow'];
export type RejectedRowPage = S['RejectedRowPage'];

export type Dataset = S['Dataset'];
export type DatasetPage = S['DatasetPage'];
export type DatasetRowPage = S['DatasetRowPage'];
export type DatasetProfile = S['DatasetProfile'];
export type MetricsSummary = S['MetricsSummary'];

export interface PageParams {
  limit?: number;
  offset?: number;
}
export interface ListRunsParams extends PageParams {
  pipeline_id?: string;
  status?: RunStatus;
}
export interface ListDatasetRowsParams extends PageParams {
  sort?: string;
  order?: 'asc' | 'desc';
}
