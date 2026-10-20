import type { RouteObject } from 'react-router-dom';
import { DatasetsPage } from '../pages/datasets/DatasetsPage';
import { HomePage } from '../pages/home/HomePage';
import { NotFoundPage } from '../pages/NotFoundPage';
import { PipelinesPage } from '../pages/pipelines/PipelinesPage';
import { RunsPage } from '../pages/runs/RunsPage';
import { SourcesPage } from '../pages/sources/SourcesPage';
import { Layout } from './Layout';

export const navItems = [
  { to: '/', label: 'Home', end: true },
  { to: '/sources', label: 'Sources', end: false },
  { to: '/pipelines', label: 'Pipelines', end: false },
  { to: '/runs', label: 'Runs', end: false },
  { to: '/datasets', label: 'Datasets', end: false },
] as const;

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'sources/*', element: <SourcesPage /> },
      { path: 'pipelines/*', element: <PipelinesPage /> },
      { path: 'runs/*', element: <RunsPage /> },
      { path: 'datasets/*', element: <DatasetsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];
