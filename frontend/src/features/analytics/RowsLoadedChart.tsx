import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { CHART_HEIGHT, color } from './ChartFrame';
import type { RowsLoadedPoint } from './format';

export function RowsLoadedChart({ points, width }: { points: RowsLoadedPoint[]; width?: number }) {
  const chart = (
    <BarChart data={points} width={width} height={width ? CHART_HEIGHT : undefined}>
      <CartesianGrid strokeDasharray="3 3" stroke={color('border')} />
      <XAxis dataKey="label" stroke={color('fg-muted')} fontSize={12} />
      <YAxis allowDecimals={false} stroke={color('fg-muted')} fontSize={12} />
      <Tooltip />
      <Legend />
      <Bar dataKey="loaded" name="Loaded" fill={color('primary')} />
      <Bar dataKey="rejected" name="Rejected" fill={color('danger')} />
    </BarChart>
  );
  return (
    <div data-testid="rows-loaded-chart">
      {width ? chart : <ResponsiveContainer width="100%" height={CHART_HEIGHT}>{chart}</ResponsiveContainer>}
      <table className="sr-only">
        <caption>Rows loaded per run</caption>
        <thead><tr><th>Run</th><th>Pipeline</th><th>Loaded</th><th>Rejected</th></tr></thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.runId}><td>{p.label}</td><td>{p.pipeline}</td><td>{p.loaded}</td><td>{p.rejected}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
