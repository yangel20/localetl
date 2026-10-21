import { DatasetExplorer } from '../../features/explorer';

export function DatasetsPage() {
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold">Datasets</h1>
      <DatasetExplorer />
    </section>
  );
}
