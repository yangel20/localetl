import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IDS, preview, source } from '../../app/api/fixtures';
import { createMockFetch, errorResponse } from '../../app/api/mockFetch';
import { routes } from '../../app/routes';
import { checkUploadFile, maxUploadBytes } from '../../components/sources/uploadRules';

let user: ReturnType<typeof userEvent.setup>;
beforeEach(() => {
  user = userEvent.setup({ delay: null });
});

type Overrides = Parameters<typeof createMockFetch>[0];

function renderAt(path: string, overrides: Overrides = {}) {
  const fetchMock = vi.fn(createMockFetch(overrides));
  vi.stubGlobal('fetch', fetchMock);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return { fetchMock, router };
}
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const csv = (name = 'x.csv', size = 10) => {
  const f = new File(['a,b\n1,2\n'], name, { type: 'text/csv' });
  Object.defineProperty(f, 'size', { value: size });
  return f;
};

afterEach(() => vi.unstubAllGlobals());

describe('source list', () => {
  it('shows a loading state, then the list', async () => {
    renderAt('/sources');
    expect(screen.getByRole('status')).toHaveTextContent('Loading sources');
    expect(await screen.findByRole('link', { name: 'orders' })).toHaveAttribute('href', `/sources/${IDS.source}`);
    expect(screen.getByText('orders.csv')).toBeInTheDocument();
  });

  it('shows the empty state', async () => {
    renderAt('/sources', { 'GET /sources': () => json({ total: 0, limit: 20, offset: 0, items: [] }) });
    expect(await screen.findByText(/No sources yet/)).toBeInTheDocument();
  });

  it('shows API errors with retry', async () => {
    let fail = true;
    renderAt('/sources', {
      'GET /sources': () =>
        fail ? errorResponse(500, 'internal_error', 'Database unavailable') : json({ total: 0, limit: 20, offset: 0, items: [] }),
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('Database unavailable');
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText(/No sources yet/)).toBeInTheDocument();
  });

  it('paginates with limit/offset', async () => {
    const items = [source];
    const { fetchMock } = renderAt('/sources', {
      'GET /sources': ({ url }) =>
        json({ total: 45, limit: 20, offset: Number(url.searchParams.get('offset')), items }),
    });
    await screen.findByText('1–20 of 45');
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('21–40 of 45');
    const urls = fetchMock.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => u.includes('limit=20') && u.includes('offset=20'))).toBe(true);
  });
});

describe('upload', () => {
  it('sends the file with the chosen CSV options and opens the preview', async () => {
    let sent: FormData | undefined;
    const { router } = renderAt('/sources', {
      'POST /sources': ({ body }) => {
        sent = body as FormData;
        return json(source, 201);
      },
    });
    await screen.findByRole('link', { name: 'orders' });
    await user.upload(screen.getByLabelText('CSV file'), csv('data.csv'));
    await user.selectOptions(screen.getByLabelText('Delimiter'), ';');
    await user.selectOptions(screen.getByLabelText('Encoding'), 'latin-1');
    await user.click(screen.getByLabelText('First row is a header'));
    await user.click(screen.getByRole('button', { name: 'Upload' }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/sources/${IDS.source}`));
    expect(sent?.get('delimiter')).toBe(';');
    expect(sent?.get('encoding')).toBe('latin-1');
    expect(sent?.get('has_header')).toBe('false');
    expect(sent?.get('quote_char')).toBe('"');
    expect((sent?.get('file') as File).name).toBe('data.csv');
    expect(sent?.has('name')).toBe(false);
  });

  it('rejects a missing, non-CSV or oversized file before any request', async () => {
    const { fetchMock } = renderAt('/sources');
    await screen.findByRole('link', { name: 'orders' });
    const post = () => fetchMock.mock.calls.filter(([, i]) => i?.method === 'POST');
    await user.click(screen.getByRole('button', { name: 'Upload' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a CSV file');

    await userEvent
      .setup({ delay: null, applyAccept: false })
      .upload(screen.getByLabelText('CSV file'), new File(['x'], 'a.txt', { type: 'text/plain' }));
    await user.click(screen.getByRole('button', { name: 'Upload' }));
    expect(screen.getByRole('alert')).toHaveTextContent('must be a CSV');

    await user.upload(screen.getByLabelText('CSV file'), csv('big.csv', 101 * 1024 * 1024));
    await user.click(screen.getByRole('button', { name: 'Upload' }));
    expect(screen.getByRole('alert')).toHaveTextContent('limit is 100.0 MB');
    expect(post()).toHaveLength(0);
  });

  it.each([
    [422, 'validation_error', 'Could not parse the file'],
    [413, 'payload_too_large', 'Upload exceeds the limit'],
    [415, 'unsupported_media_type', 'File is not a CSV'],
  ])('shows the server message verbatim for HTTP %i', async (status, code, message) => {
    renderAt('/sources', { 'POST /sources': () => errorResponse(status, code, message) });
    await screen.findByRole('link', { name: 'orders' });
    await user.upload(screen.getByLabelText('CSV file'), csv());
    await user.click(screen.getByRole('button', { name: 'Upload' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.getByRole('button', { name: 'Upload' })).toBeEnabled();
  });
});

describe('upload rules', () => {
  it('honours VITE_MAX_UPLOAD_MB with a 100 MB default', () => {
    expect(maxUploadBytes(undefined)).toBe(100 * 1024 * 1024);
    expect(maxUploadBytes('abc')).toBe(100 * 1024 * 1024);
    expect(maxUploadBytes('5')).toBe(5 * 1024 * 1024);
    expect(checkUploadFile(csv('a.csv', 6 * 1024 * 1024), 5 * 1024 * 1024)).toMatch(/limit/);
    expect(checkUploadFile(csv('A.CSV', 10))).toBeNull();
  });
});

describe('source preview', () => {
  it('renders the columns, types and rows as a table', async () => {
    renderAt(`/sources/${IDS.source}`);
    expect(screen.getByRole('status')).toHaveTextContent('Loading preview');
    expect(await screen.findByRole('heading', { level: 1, name: 'orders' })).toBeInTheDocument();
    const table = screen.getByRole('table');
    expect(within(table).getByRole('columnheader', { name: /customer/ })).toBeInTheDocument();
    expect(within(table).getByText('Ada')).toBeInTheDocument();
    expect(within(table).getByText('(empty)')).toBeInTheDocument();
  });

  it('renders cell values as text, never as HTML', async () => {
    const evil = '<img src=x onerror="alert(1)"><b>bold</b>';
    renderAt(`/sources/${IDS.source}`, {
      'GET /sources/[^/]+/preview': () =>
        json({ ...preview, rows: [{ order_id: '1', customer: evil, amount: '1' }], sampled_rows: 1 }),
    });
    const cell = await screen.findByText(evil);
    expect(cell.tagName).toBe('TD');
    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('td b')).toBeNull();
  });

  it('shows an empty state when there are no rows', async () => {
    renderAt(`/sources/${IDS.source}`, {
      'GET /sources/[^/]+/preview': () => json({ ...preview, rows: [], sampled_rows: 0 }),
    });
    expect(await screen.findByText('This source has no data rows.')).toBeInTheDocument();
  });

  it('shows a 404 error', async () => {
    renderAt(`/sources/${IDS.source}`, {
      'GET /sources/[^/]+': () => errorResponse(404, 'not_found', 'Source not found'),
      'GET /sources/[^/]+/preview': () => errorResponse(404, 'not_found', 'Source not found'),
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('Source not found');
  });
});
