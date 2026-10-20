import { describe, expect, it, vi } from 'vitest';
import { createApiClient } from './client';
import { ApiError } from './errors';
import { IDS } from './fixtures';
import { createMockFetch, errorResponse } from './mockFetch';
import type { PipelineCreate } from './types';

const BASE = 'http://api.test/api/v1';

function spyFetch(res: () => Response) {
  const spy = vi.fn<typeof fetch>(async () => res());
  return { spy, client: createApiClient({ baseUrl: BASE, fetch: spy }) };
}
const lastCall = (spy: ReturnType<typeof vi.fn<typeof fetch>>) => {
  const [url, init] = spy.mock.calls.at(-1)!;
  return { url: String(url), init: init! };
};

describe('api client', () => {
  it('uses the base URL and trims trailing slashes', async () => {
    const { spy } = spyFetch(() => errorResponse(500, 'internal_error', 'x'));
    const c = createApiClient({ baseUrl: `${BASE}//`, fetch: spy });
    expect(c.baseUrl).toBe(BASE);
    await c.getHealth().catch(() => undefined);
    expect(lastCall(spy).url).toBe(`${BASE}/health`);
  });

  it('serialises query parameters and skips undefined', async () => {
    const client = createApiClient({ baseUrl: BASE, fetch: createMockFetch() });
    const spy = vi.fn(createMockFetch());
    const c = createApiClient({ baseUrl: BASE, fetch: spy });
    await c.listRuns({ status: 'running', pipeline_id: IDS.pipeline, limit: 10, offset: undefined });
    const { url } = lastCall(spy);
    expect(url).toContain('/runs?');
    expect(url).toContain('status=running');
    expect(url).toContain('limit=10');
    expect(url).not.toContain('offset');
    expect((await client.listRuns()).items).toHaveLength(2);
  });

  it('surfaces the Error body as a typed ApiError', async () => {
    const { client } = spyFetch(() =>
      errorResponse(409, 'conflict', 'Pipeline already has an active run'),
    );
    const err = await client.createRun(IDS.pipeline).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: 'conflict', message: 'Pipeline already has an active run' });
  });

  it('keeps validation details with their JSON Pointer paths', async () => {
    const { client } = spyFetch(() =>
      errorResponse(422, 'validation_error', 'bad', [{ path: '/config/columns/0/name', message: 'invalid' }]),
    );
    const err = (await client.listSources().catch((e: unknown) => e)) as ApiError;
    expect(err.details).toEqual([{ path: '/config/columns/0/name', message: 'invalid' }]);
  });

  it('maps a non-contract error body to invalid_response', async () => {
    const { client } = spyFetch(() => new Response('<html>oops</html>', { status: 502 }));
    await expect(client.getHealth()).rejects.toMatchObject({ status: 502, code: 'invalid_response' });
  });

  it('maps transport failures to network_error', async () => {
    const client = createApiClient({
      baseUrl: BASE,
      fetch: async () => {
        throw new TypeError('Failed to fetch');
      },
    });
    await expect(client.getHealth()).rejects.toMatchObject({ status: 0, code: 'network_error' });
  });

  it('returns undefined for 204 deletes', async () => {
    const { spy, client } = spyFetch(() => new Response(null, { status: 204 }));
    await expect(client.deleteSource(IDS.source)).resolves.toBeUndefined();
    expect(lastCall(spy).init.method).toBe('DELETE');
  });

  it('posts JSON bodies with a content type', async () => {
    const { spy, client } = spyFetch(() => new Response(JSON.stringify({ valid: true, errors: [] })));
    await client.validatePipelineConfig({ anything: 1 }, IDS.source);
    const { url, init } = lastCall(spy);
    expect(url).toBe(`${BASE}/pipelines/validate`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ config: { anything: 1 }, source_id: IDS.source });
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('uploads sources as multipart without a manual content type', async () => {
    const { spy, client } = spyFetch(() => new Response('{}', { status: 201 }));
    const file = new File(['a,b\n1,2\n'], 'x.csv', { type: 'text/csv' });
    await client.createSource(file, { delimiter: ';', has_header: false, name: undefined });
    const { init } = lastCall(spy);
    const form = init.body as FormData;
    expect(form.get('file')).toBeInstanceOf(File);
    expect(form.get('delimiter')).toBe(';');
    expect(form.get('has_header')).toBe('false');
    expect(form.has('name')).toBe(false);
    expect((init.headers as Record<string, string>)['Content-Type']).toBeUndefined();
  });

  it('sends pipeline create/update bodies typed against the contract', async () => {
    const { spy, client } = spyFetch(() => new Response('{}', { status: 200 }));
    const body: PipelineCreate = {
      name: 'p',
      source_id: IDS.source,
      config: {
        version: 1,
        columns: [{ source: 'id', name: 'id', type: 'integer' }],
        target: { table: 'minimal', mode: 'replace' },
      },
    };
    await client.updatePipeline(IDS.pipeline, body);
    expect(lastCall(spy).init.method).toBe('PUT');
    expect(lastCall(spy).url).toBe(`${BASE}/pipelines/${IDS.pipeline}`);
  });

  it('serves every read operation from fixtures via the mock fetch', async () => {
    const c = createApiClient({ baseUrl: BASE, fetch: createMockFetch() });
    expect((await c.getHealth()).status).toBe('ok');
    expect((await c.previewSource(IDS.source, 10)).sampled_rows).toBe(2);
    expect((await c.getRun(IDS.runRunning)).status).toBe('running');
    expect(await c.listRunEvents(IDS.runSucceeded)).toHaveLength(6);
    expect((await c.listRunRejections(IDS.runSucceeded)).total).toBe(1);
    expect((await c.getDatasetProfile(IDS.dataset)).columns.length).toBeGreaterThan(0);
    expect((await c.getMetricsSummary(7)).total_runs).toBe(2);
    expect((await c.createRun(IDS.pipeline)).status).toBe('queued');
    await expect(c.getPipeline(IDS.pipeline)).resolves.toMatchObject({ config_version: 1 });
  });

  it('fixture run counters satisfy the Q3 accounting identity', async () => {
    const c = createApiClient({ baseUrl: BASE, fetch: createMockFetch() });
    const r = await c.getRun(IDS.runSucceeded);
    expect(r.extracted_count).toBe(
      r.loaded_count + r.rejected_count + r.duplicate_dropped_count + r.null_dropped_count,
    );
  });
});
