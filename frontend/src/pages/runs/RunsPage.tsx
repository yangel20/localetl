import { Route, Routes } from 'react-router-dom';
import { RunDetailPage } from './RunDetailPage';
import { RunListPage } from './RunListPage';

export function RunsPage() {
  return (
    <Routes>
      <Route index element={<RunListPage />} />
      <Route path=":runId" element={<RunDetailPage />} />
    </Routes>
  );
}
