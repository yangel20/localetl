import type { ApiError } from '../app/api/errors';

interface Props {
  error: Pick<ApiError, 'message' | 'details'>;
  onRetry?: () => void;
}

/** Shows the API error message exactly as returned, plus per-path details when present. */
export function ErrorMessage({ error, onRetry }: Props) {
  return (
    <div role="alert" className="rounded border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
      <p>{error.message}</p>
      {error.details.length > 0 && (
        <ul className="mt-1 list-disc pl-5">
          {error.details.map((d, i) => (
            <li key={`${d.path}-${i}`}>
              <code>{d.path}</code>: {d.message}
            </li>
          ))}
        </ul>
      )}
      {onRetry && (
        <button type="button" onClick={onRetry} className="mt-2 underline">
          Retry
        </button>
      )}
    </div>
  );
}
