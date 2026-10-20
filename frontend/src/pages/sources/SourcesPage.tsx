import { Route, Routes } from 'react-router-dom';
import { SourceDetailPage } from './SourceDetailPage';
import { SourceListPage } from './SourceListPage';

export function SourcesPage() {
  return (
    <Routes>
      <Route index element={<SourceListPage />} />
      <Route path=":sourceId" element={<SourceDetailPage />} />
    </Routes>
  );
}
