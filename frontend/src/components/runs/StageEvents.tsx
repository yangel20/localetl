import type { RunEvent } from '../../app/api/types';

export function StageEvents({ events }: { events: RunEvent[] }) {
  if (events.length === 0) return <p className="text-fg-muted">No stage events yet.</p>;
  return (
    <div className="overflow-x-auto rounded border border-border">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-surface-muted">
          <tr>
            <th scope="col" className="px-3 py-2">Time</th>
            <th scope="col" className="px-3 py-2">Stage</th>
            <th scope="col" className="px-3 py-2">Status</th>
            <th scope="col" className="px-3 py-2">Rows in</th>
            <th scope="col" className="px-3 py-2">Rows out</th>
            <th scope="col" className="px-3 py-2">Message</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id} className="border-t border-border">
              <td className="px-3 py-1.5">{new Date(e.created_at).toLocaleTimeString()}</td>
              <td className="px-3 py-1.5">{e.stage}</td>
              <td className="px-3 py-1.5">{e.status}</td>
              <td className="px-3 py-1.5">{e.rows_in ?? '—'}</td>
              <td className="px-3 py-1.5">{e.rows_out ?? '—'}</td>
              <td className="px-3 py-1.5">{e.message ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
