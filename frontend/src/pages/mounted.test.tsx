import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createMockFetch } from '../app/api/mockFetch';
import { routes } from '../app/routes';

afterEach(() => vi.unstubAllGlobals());

function renderAt(path: string) {
  vi.stubGlobal('fetch', vi.fn(createMockFetch()));
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
}

describe('mounted viz screens', () => {
  it('Home renders RunAnalytics', async () => {
    renderAt('/');
    expect(await screen.findByLabelText('Run statistics')).toBeInTheDocument();
  });

  it('Datasets renders DatasetExplorer with the fixture dataset', async () => {
    renderAt('/datasets');
    expect(screen.getByTestId('dataset-explorer')).toBeInTheDocument();
    expect(await screen.findByRole('button', { pressed: false })).toBeInTheDocument();
  });
});
