import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { DatasetProfile } from '../../app/api/types';
import { color } from '../analytics/ChartFrame';
import { formatCell, nullPercent, toNullSplit, toTopValuePoints } from './format';

const H = 180;

function ColumnProfileCard({ col, rowCount, width }: { col: DatasetProfile['columns'][number]; rowCount: number; width?: number }) {
  const top = toTopValuePoints(col);
  const split = toNullSplit(col, rowCount);
  const wrap = (node: React.ReactElement) =>
    width ? node : <ResponsiveContainer width="100%" height={H}>{node}</ResponsiveContainer>;
  return (
    <section aria-label={`Profile of ${col.name}`} className="rounded border border-border bg-surface p-3">
      <h4 className="text-sm font-semibold">{col.name} <span className="font-normal text-fg-muted">({col.type})</span></h4>
      <p className="text-xs text-fg-muted">
        {nullPercent(col.null_count, rowCount)} null · {col.distinct_count} distinct
        {col.min !== null && col.max !== null && <> · range {formatCell(col.min)} – {formatCell(col.max)}</>}
      </p>
      <div className="grid gap-2 md:grid-cols-2">
        <div data-testid={`top-values-${col.name}`}>
          {top.length === 0 ? <p className="text-sm text-fg-muted">No values.</p> : wrap(
            <BarChart data={top} layout="vertical" width={width} height={width ? H : undefined}>
              <CartesianGrid strokeDasharray="3 3" stroke={color('border')} />
              <XAxis type="number" allowDecimals={false} stroke={color('fg-muted')} fontSize={12} />
              <YAxis type="category" dataKey="label" width={80} stroke={color('fg-muted')} fontSize={12} />
              <Tooltip />
              <Bar dataKey="count" name="Count" fill={color('primary')} />
            </BarChart>,
          )}
        </div>
        <div data-testid={`nulls-${col.name}`}>
          {wrap(
            <PieChart width={width} height={width ? H : undefined}>
              <Pie data={split} dataKey="count" nameKey="name" innerRadius={30} outerRadius={60}>
                <Cell fill={color('primary')} />
                <Cell fill={color('warning')} />
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>,
          )}
        </div>
      </div>
      <table className="sr-only">
        <caption>Top values of {col.name}</caption>
        <thead><tr><th>Value</th><th>Count</th></tr></thead>
        <tbody>{top.map((t, i) => <tr key={i}><td>{t.label}</td><td>{t.count}</td></tr>)}</tbody>
      </table>
    </section>
  );
}

export function ProfileCharts({ profile, width }: { profile: DatasetProfile; width?: number }) {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {profile.columns.map((c) => <ColumnProfileCard key={c.name} col={c} rowCount={profile.row_count} width={width} />)}
    </div>
  );
}
