import { RunAnalytics } from '../../features/analytics';

export function HomePage() {
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold">Home</h1>
      <RunAnalytics />
    </section>
  );
}
