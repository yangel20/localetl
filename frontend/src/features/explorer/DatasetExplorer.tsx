import { useState } from 'react';
import { api as defaultApi, type ApiClient } from '../../app/api/client';
import { ChartFrame } from '../analytics/ChartFrame';
import { useApiData } from '../analytics/useApiData';
import { formatCount } from '../analytics/format';
import type { SortState } from './format';
import { ProfileCharts } from './ProfileCharts';
import { RowsTable } from './RowsTable';

const PAGE_SIZE = 25;
type Client = Pick<ApiClient, 'listDatasets' | 'listDatasetRows' | 'getDatasetProfile'>;

function Selected({ client, id, width }: { client: Client; id: string; width?: number }) {
  const [sort, setSort] = useState<SortState | null>(null);
  const [offset, setOffset] = useState(0);
  const rows = useApiData(
    (s) => client.listDatasetRows(id, { limit: PAGE_SIZE, offset, ...(sort ?? {}) }, s),
    [client, id, offset, sort?.column, sort?.order],
  );
  const profile = useApiData((s) => client.getDatasetProfile(id, s), [client, id]);
  return (
    <div className="flex flex-col gap-4">
      <ChartFrame title="Rows" state={rows} isEmpty={() => false} emptyText="">
        {(page) => (
          <RowsTable page={page} sort={sort} onSort={(s) => { setSort(s); setOffset(0); }} onOffset={setOffset} />
        )}
      </ChartFrame>
      <ChartFrame title="Column profiles" state={profile} isEmpty={(p) => p.columns.length === 0} emptyText="No columns to profile.">
        {(p) => <ProfileCharts profile={p} width={width} />}
      </ChartFrame>
    </div>
  );
}

/** Datasets list + rows preview + profile charts (REQ-53..55). Mount point for the Datasets page. */
export function DatasetExplorer({ client = defaultApi, width }: { client?: Client; width?: number }) {
  const list = useApiData((s) => client.listDatasets({ limit: 100 }, s), [client]);
  const [picked, setPicked] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-4" data-testid="dataset-explorer">
      <ChartFrame title="Datasets" state={list} isEmpty={(p) => p.items.length === 0} emptyText="No published datasets yet. Run a pipeline to publish one.">
        {(p) => (
          <ul className="flex flex-col gap-1">
            {p.items.map((d) => (
              <li key={d.id}>
                <button type="button" aria-pressed={picked === d.id} onClick={() => setPicked(d.id)}
                  className="w-full rounded border border-border px-2 py-1 text-left text-sm aria-pressed:border-primary">
                  <strong>{d.table_name}</strong>{' '}
                  <span className="text-fg-muted">
                    {formatCount(d.row_count)} rows · {d.columns.length} columns · published {new Date(d.published_at).toISOString().slice(0, 16).replace('T', ' ')} UTC
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </ChartFrame>
      {picked && <Selected key={picked} client={client} id={picked} width={width} />}
    </div>
  );
}
