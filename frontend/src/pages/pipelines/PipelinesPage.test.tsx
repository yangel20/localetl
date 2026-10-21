import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IDS, pipeline } from '../../app/api/fixtures';
import { createMockFetch, errorResponse } from '../../app/api/mockFetch';
import { routes } from '../../app/routes';

let user: ReturnType<typeof userEvent.setup>;
beforeEach(() => {
  user = userEvent.setup({ delay: null });
});

type Overrides = Parameters<typeof createMockFetch>[0];
const json = (b: unknown, status = 200) =>
  new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } });
const emptyPage = { total: 0, limit: 20, offset: 0, items: [] };

function renderAt(path: string, overrides: Overrides = {}) {
  const fetchMock = vi.fn(createMockFetch(overrides));
  vi.stubGlobal('fetch', fetchMock);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return { fetchMock, router };
}
afterEach(() => vi.unstubAllGlobals());

describe('pipeline list', () => {
  it('loads, then lists pipelines with last run status and links', async () => {
    renderAt('/pipelines');
    expect(screen.getByRole('status')).toHaveTextContent('Loading pipelines');
    const link = await screen.findByRole('link', { name: 'Orders cleanup' });
    expect(link).toHaveAttribute('href', `/pipelines/${IDS.pipeline}`);
    expect(screen.getByText('orders_clean (replace)')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'succeeded' })).toHaveAttribute('href', `/runs/${IDS.runSucceeded}`);
    expect(screen.getByRole('link', { name: 'New pipeline' })).toHaveAttribute('href', '/pipelines/new');
  });

  it('shows empty and error states', async () => {
    renderAt('/pipelines', { 'GET /pipelines': () => json(emptyPage) });
    expect(await screen.findByText(/No pipelines yet/)).toBeInTheDocument();
    vi.unstubAllGlobals();
    renderAt('/pipelines', { 'GET /pipelines': () => errorResponse(500, 'internal_error', 'db down') });
    expect(await screen.findByText('db down')).toBeInTheDocument();
  });

  it('paginates', async () => {
    const { fetchMock } = renderAt('/pipelines', {
      'GET /pipelines': ({ url }) => json({ total: 30, limit: 20, offset: Number(url.searchParams.get('offset')), items: [pipeline] }),
    });
    await screen.findByText('1–20 of 30');
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('21–30 of 30');
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('offset=20'))).toBe(true);
  });

  it('deletes after confirmation and reloads', async () => {
    let items = [pipeline];
    const { fetchMock } = renderAt('/pipelines', {
      'GET /pipelines': () => json({ total: items.length, limit: 20, offset: 0, items }),
      'DELETE /pipelines/[^/]+': () => {
        items = [];
        return new Response(null, { status: 204 });
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Delete Orders cleanup' }));
    expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'DELETE')).toBe(false); // needs confirmation
    await user.click(screen.getByRole('button', { name: 'Confirm delete Orders cleanup' }));
    expect(await screen.findByText(/No pipelines yet/)).toBeInTheDocument();
  });

  it('shows the 409 message clearly when a run is active', async () => {
    renderAt('/pipelines', {
      'DELETE /pipelines/[^/]+': () => errorResponse(409, 'conflict', 'Pipeline has a queued or running run'),
    });
    await user.click(await screen.findByRole('button', { name: 'Delete Orders cleanup' }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete Orders cleanup' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Pipeline has a queued or running run');
    expect(screen.getByRole('link', { name: 'Orders cleanup' })).toBeInTheDocument(); // still listed
  });
});

describe('new pipeline', () => {
  it('sends users without sources to upload', async () => {
    renderAt('/pipelines/new', { 'GET /sources': () => json(emptyPage) });
    expect(await screen.findByRole('link', { name: /Upload a CSV first/ })).toHaveAttribute('href', '/sources');
  });

  it('creates a pipeline and returns to the list', async () => {
    let created: { name: string; config: { columns: unknown[] } } | undefined;
    const { router } = renderAt('/pipelines/new', {
      'POST /pipelines': ({ body }) => {
        created = body as typeof created;
        return json(pipeline, 201);
      },
    });
    await user.click(await screen.findByLabelText('Name'));
    await user.paste('Fresh');
    await user.selectOptions(screen.getByLabelText('Data source'), 'orders');
    await user.click(screen.getByLabelText('Target table'));
    await user.paste('fresh_out');
    await user.click(screen.getByRole('button', { name: 'Create pipeline' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/pipelines'));
    expect(created?.name).toBe('Fresh');
    expect(created?.config.columns).toHaveLength(3);
  });

  it('shows a duplicate-name 409 from the server and stays on the page', async () => {
    const { router } = renderAt('/pipelines/new', {
      'POST /pipelines': () => errorResponse(409, 'conflict', 'A pipeline with this name already exists'),
    });
    await user.click(await screen.findByLabelText('Name'));
    await user.paste('Dup');
    await user.selectOptions(screen.getByLabelText('Data source'), 'orders');
    await user.click(screen.getByLabelText('Target table'));
    await user.paste('dup_out');
    await user.click(screen.getByRole('button', { name: 'Create pipeline' }));
    expect(await screen.findByText('A pipeline with this name already exists')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/pipelines/new');
  });
});

describe('edit pipeline', () => {
  it('loads the saved config into the form', async () => {
    renderAt(`/pipelines/${IDS.pipeline}`);
    expect(screen.getByRole('status')).toHaveTextContent('Loading pipeline');
    expect(await screen.findByRole('heading', { level: 1, name: 'Edit Orders cleanup' })).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Orders cleanup');
    expect(screen.getByLabelText('Target table')).toHaveValue('orders_clean');
    const t = screen.getByRole('listitem', { name: /Transformation 1: Trim whitespace/ });
    expect(within(t).getByLabelText('customer')).toBeChecked();
  });

  it('saves with PUT and reports the new version', async () => {
    let put: { name: string } | undefined;
    const { fetchMock } = renderAt(`/pipelines/${IDS.pipeline}`, {
      'PUT /pipelines/[^/]+': ({ body }) => {
        put = body as typeof put;
        return json({ ...pipeline, config_version: 2 });
      },
    });
    const name = await screen.findByLabelText('Name');
    await user.clear(name);
    await user.click(name);
    await user.paste('Renamed');
    await user.click(screen.getByRole('button', { name: 'Save pipeline' }));
    expect(await screen.findByText('Saved (version 2).')).toBeInTheDocument();
    expect(put?.name).toBe('Renamed');
    expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'PUT')).toBe(true);
  });

  it('shows 404 errors', async () => {
    renderAt(`/pipelines/${IDS.pipeline}`, { 'GET /pipelines/[^/]+': () => errorResponse(404, 'not_found', 'Pipeline not found') });
    expect(await screen.findByRole('alert')).toHaveTextContent('Pipeline not found');
  });

  it('maps a server 422 back to the field', async () => {
    renderAt(`/pipelines/${IDS.pipeline}`, {
      'PUT /pipelines/[^/]+': () =>
        errorResponse(422, 'validation_error', 'Invalid config', [{ path: '/config/target/table', message: 'reserved name' }]),
    });
    await user.click(await screen.findByRole('button', { name: 'Save pipeline' }));
    await screen.findByText('Invalid config');
    expect(document.querySelector('[data-path="/target/table"]')).toHaveTextContent('reserved name');
  });
});
