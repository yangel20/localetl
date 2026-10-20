import { IDS } from './fixtures';
import * as fx from './fixtures';

type Handler = (req: { url: URL; method: string; body: unknown }) => Response;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export function errorResponse(
  status: number,
  code: string,
  message: string,
  details: { path: string; message: string }[] = [],
): Response {
  return json({ error: { code, message, ...(details.length ? { details } : {}) } }, status);
}

function page<T>(items: T[], url: URL) {
  return {
    total: items.length,
    limit: Number(url.searchParams.get('limit') ?? 50),
    offset: Number(url.searchParams.get('offset') ?? 0),
    items,
  };
}

const routes: [string, RegExp, Handler][] = [
  ['GET', /^\/health$/, () => json(fx.health)],
  ['GET', /^\/sources$/, ({ url }) => json(page([fx.source], url))],
  ['GET', /^\/sources\/[^/]+$/, () => json(fx.source)],
  ['GET', /^\/sources\/[^/]+\/preview$/, () => json(fx.preview)],
  ['POST', /^\/pipelines\/validate$/, () => json({ valid: true, errors: [] })],
  ['GET', /^\/pipelines$/, ({ url }) => json(page([fx.pipeline], url))],
  ['GET', /^\/pipelines\/[^/]+$/, () => json(fx.pipeline)],
  ['POST', /^\/pipelines\/[^/]+\/runs$/, () => json({ ...fx.runRunning, status: 'queued' }, 202)],
  ['GET', /^\/runs$/, ({ url }) => json(page([fx.runRunning, fx.runSucceeded], url))],
  ['GET', /^\/runs\/[^/]+$/, ({ url }) =>
    json(url.pathname.endsWith(IDS.runRunning) ? fx.runRunning : fx.runSucceeded)],
  ['GET', /^\/runs\/[^/]+\/events$/, () => json(fx.runEvents)],
  ['GET', /^\/runs\/[^/]+\/rejections$/, () => json(fx.rejections)],
  ['GET', /^\/datasets$/, ({ url }) => json(page([fx.dataset], url))],
  ['GET', /^\/datasets\/[^/]+$/, () => json(fx.dataset)],
  ['GET', /^\/datasets\/[^/]+\/rows$/, () => json(fx.datasetRows)],
  ['GET', /^\/datasets\/[^/]+\/profile$/, () => json(fx.datasetProfile)],
  ['GET', /^\/metrics\/summary$/, () => json(fx.metricsSummary)],
];

/**
 * A `fetch` replacement serving fixtures, for tests and for developing against
 * endpoints the backend does not provide yet. `overrides` ("METHOD /path/regex-source") win.
 */
export function createMockFetch(overrides: Record<string, Handler> = {}): typeof fetch {
  return async (input, init) => {
    const url = new URL(String(input));
    const method = (init?.method ?? 'GET').toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, '');
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body;
    for (const [key, handler] of Object.entries(overrides)) {
      const [m, p] = key.split(' ');
      if (m === method && new RegExp(`^${p}$`).test(path)) return handler({ url, method, body });
    }
    for (const [m, re, handler] of routes) {
      if (m === method && re.test(path)) return handler({ url, method, body });
    }
    if (method === 'DELETE') return new Response(null, { status: 204 });
    return errorResponse(404, 'not_found', `No mock for ${method} ${path}`);
  };
}
