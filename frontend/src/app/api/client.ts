import { ApiError } from './errors';
import type {
  CsvPreview,
  DataSource,
  DataSourcePage,
  Dataset,
  DatasetPage,
  DatasetProfile,
  DatasetRowPage,
  Health,
  ListDatasetRowsParams,
  ListRunsParams,
  MetricsSummary,
  PageParams,
  Pipeline,
  PipelineCreate,
  PipelinePage,
  PipelineValidationResult,
  RejectedRowPage,
  Run,
  RunEvent,
  RunPage,
  SourceUploadOptions,
} from './types';

export const DEFAULT_API_URL = 'http://127.0.0.1:8000/api/v1';

type Query = Record<string, string | number | boolean | undefined>;
type FetchLike = typeof fetch;

export interface ClientOptions {
  /** Defaults to `VITE_API_URL`, then `DEFAULT_API_URL`. */
  baseUrl?: string;
  /** Injectable for tests and mock mode. */
  fetch?: FetchLike;
}

interface RequestInit2 {
  query?: Query;
  json?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

const enc = encodeURIComponent;

function resolveBaseUrl(explicit?: string): string {
  const raw = explicit ?? import.meta.env.VITE_API_URL ?? DEFAULT_API_URL;
  return raw.replace(/\/+$/, '');
}

function buildQuery(query?: Query): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : '';
}

async function toApiError(res: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = undefined;
  }
  const err = (body as { error?: { code?: string; message?: string; details?: unknown } } | undefined)
    ?.error;
  if (err && typeof err.code === 'string' && typeof err.message === 'string') {
    return new ApiError(
      res.status,
      err.code as ApiError['code'],
      err.message,
      Array.isArray(err.details) ? (err.details as ApiError['details']) : [],
    );
  }
  return new ApiError(
    res.status,
    'invalid_response',
    `Unexpected response (HTTP ${res.status}) without an API error body`,
  );
}

export function createApiClient(options: ClientOptions = {}) {
  const baseUrl = resolveBaseUrl(options.baseUrl);
  // Resolved lazily so stubbing globalThis.fetch after construction still works.
  const doFetch: FetchLike = (input, init) => (options.fetch ?? globalThis.fetch)(input, init);

  async function request<T>(method: string, path: string, init: RequestInit2 = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    let body: BodyInit | undefined;
    if (init.form) {
      body = init.form; // the browser sets the multipart boundary
    } else if (init.json !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(init.json);
    }
    let res: Response;
    try {
      res = await doFetch(`${baseUrl}${path}${buildQuery(init.query)}`, {
        method,
        headers,
        body,
        signal: init.signal,
      });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
      throw new ApiError(0, 'network_error', 'Could not reach the API. Is the backend running?');
    }
    if (!res.ok) throw await toApiError(res);
    if (res.status === 204) return undefined as T;
    try {
      return (await res.json()) as T;
    } catch {
      throw new ApiError(res.status, 'invalid_response', 'The API returned a malformed JSON body');
    }
  }

  const get = <T>(path: string, query?: Query, signal?: AbortSignal) =>
    request<T>('GET', path, { query, signal });

  return {
    baseUrl,

    // system
    getHealth: (signal?: AbortSignal) => get<Health>('/health', undefined, signal),

    // sources
    createSource(file: File | Blob, options: SourceUploadOptions = {}, filename?: string) {
      const form = new FormData();
      if (filename !== undefined) form.append('file', file, filename);
      else form.append('file', file);
      for (const [key, value] of Object.entries(options)) {
        if (value !== undefined) form.append(key, String(value));
      }
      return request<DataSource>('POST', '/sources', { form });
    },
    listSources: (params: PageParams = {}, signal?: AbortSignal) =>
      get<DataSourcePage>('/sources', { ...params }, signal),
    getSource: (id: string, signal?: AbortSignal) =>
      get<DataSource>(`/sources/${enc(id)}`, undefined, signal),
    deleteSource: (id: string) => request<void>('DELETE', `/sources/${enc(id)}`),
    previewSource: (id: string, limit?: number, signal?: AbortSignal) =>
      get<CsvPreview>(`/sources/${enc(id)}/preview`, { limit }, signal),

    // pipelines
    createPipeline: (body: PipelineCreate) => request<Pipeline>('POST', '/pipelines', { json: body }),
    listPipelines: (params: PageParams = {}, signal?: AbortSignal) =>
      get<PipelinePage>('/pipelines', { ...params }, signal),
    /** `config` is deliberately `unknown`: invalid configs must reach the server validator. */
    validatePipelineConfig: (config: unknown, sourceId?: string) =>
      request<PipelineValidationResult>('POST', '/pipelines/validate', {
        json: { config, ...(sourceId ? { source_id: sourceId } : {}) },
      }),
    getPipeline: (id: string, signal?: AbortSignal) =>
      get<Pipeline>(`/pipelines/${enc(id)}`, undefined, signal),
    updatePipeline: (id: string, body: PipelineCreate) =>
      request<Pipeline>('PUT', `/pipelines/${enc(id)}`, { json: body }),
    deletePipeline: (id: string) => request<void>('DELETE', `/pipelines/${enc(id)}`),

    // runs
    createRun: (pipelineId: string) => request<Run>('POST', `/pipelines/${enc(pipelineId)}/runs`),
    listRuns: (params: ListRunsParams = {}, signal?: AbortSignal) =>
      get<RunPage>('/runs', { ...params }, signal),
    getRun: (id: string, signal?: AbortSignal) => get<Run>(`/runs/${enc(id)}`, undefined, signal),
    listRunEvents: (id: string, signal?: AbortSignal) =>
      get<RunEvent[]>(`/runs/${enc(id)}/events`, undefined, signal),
    listRunRejections: (id: string, params: PageParams = {}, signal?: AbortSignal) =>
      get<RejectedRowPage>(`/runs/${enc(id)}/rejections`, { ...params }, signal),

    // datasets
    listDatasets: (params: PageParams = {}, signal?: AbortSignal) =>
      get<DatasetPage>('/datasets', { ...params }, signal),
    getDataset: (id: string, signal?: AbortSignal) =>
      get<Dataset>(`/datasets/${enc(id)}`, undefined, signal),
    listDatasetRows: (id: string, params: ListDatasetRowsParams = {}, signal?: AbortSignal) =>
      get<DatasetRowPage>(`/datasets/${enc(id)}/rows`, { ...params }, signal),
    getDatasetProfile: (id: string, signal?: AbortSignal) =>
      get<DatasetProfile>(`/datasets/${enc(id)}/profile`, undefined, signal),

    // metrics
    getMetricsSummary: (days?: number, signal?: AbortSignal) =>
      get<MetricsSummary>('/metrics/summary', { days }, signal),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

/** Shared default client for the app. */
export const api: ApiClient = createApiClient();
