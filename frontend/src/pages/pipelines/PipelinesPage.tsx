import { Route, Routes } from 'react-router-dom';
import { PipelineEditPage } from './PipelineEditPage';
import { PipelineListPage } from './PipelineListPage';
import { PipelineNewPage } from './PipelineNewPage';

export function PipelinesPage() {
  return (
    <Routes>
      <Route index element={<PipelineListPage />} />
      <Route path="new" element={<PipelineNewPage />} />
      <Route path=":pipelineId" element={<PipelineEditPage />} />
    </Routes>
  );
}
