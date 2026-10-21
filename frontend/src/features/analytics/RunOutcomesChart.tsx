import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { MetricsSummary } from '../../app/api/types';
import { CHART_HEIGHT, color } from './ChartFrame';
import { toOutcomeRows } from './format';

/** Stacked daily run outcomes. `width` is for tests (jsdom has no layout). */
export function RunOutcomesChart({ daily, width }: { daily: MetricsSummary['daily']; width?: number }) {
  const rows = toOutcomeRows(daily);
  const chart = (
    <BarChart data={rows} width={width} height={width ? CHART_HEIGHT : undefined}>
      <CartesianGrid strokeDasharray="3 3" stroke={color('border')} />
      <XAxis dataKey="label" stroke={color('fg-muted')} fontSize={12} />
      <YAxis allowDecimals={false} stroke={color('fg-muted')} fontSize={12} />
      <Tooltip />
      <Legend />
      <Bar dataKey="succeeded" name="Succeeded" stackId="o" fill={color('success')} />
      <Bar dataKey="failed" name="Failed" stackId="o" fill={color('danger')} />
      <Bar dataKey="interrupted" name="Interrupted" stackId="o" fill={color('warning')} />
    </BarChart>
  );
  return (
    <div data-testid="run-outcomes-chart">
      {width ? chart : <ResponsiveContainer width="100%" height={CHART_HEIGHT}>{chart}</ResponsiveContainer>}
      <table className="sr-only">
        <caption>Run outcomes per day</caption>
        <thead><tr><th>Day</th><th>Succeeded</th><th>Failed</th><th>Interrupted</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.date}><td>{r.label}</td><td>{r.succeeded}</td><td>{r.failed}</td><td>{r.interrupted}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
