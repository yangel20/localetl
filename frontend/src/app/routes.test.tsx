import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { routes } from './routes';

function renderAt(path: string) {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
}

describe('app shell', () => {
  it.each([
    ['/', 'Home'],
    ['/sources', 'Sources'],
    ['/pipelines', 'Pipelines'],
    ['/runs', 'Runs'],
    ['/datasets', 'Datasets'],
  ])('renders %s', (path, heading) => {
    renderAt(path);
    expect(screen.getByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
  });

  it('shows not found for unknown routes', () => {
    renderAt('/nope');
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });

  it('navigates via the sidebar', async () => {
    renderAt('/');
    await userEvent.click(screen.getByRole('link', { name: 'Runs' }));
    expect(screen.getByRole('heading', { level: 1, name: 'Runs' })).toBeInTheDocument();
  });
});
