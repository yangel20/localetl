const DEFAULT_MAX_MB = 100; // matches LOCALETL_MAX_UPLOAD_MB's default

export function maxUploadBytes(env: string | undefined = import.meta.env.VITE_MAX_UPLOAD_MB): number {
  const mb = Number(env);
  return (Number.isFinite(mb) && mb > 0 ? mb : DEFAULT_MAX_MB) * 1024 * 1024;
}

/** Client-side pre-checks; the server stays authoritative. Returns an error message or null. */
export function checkUploadFile(file: File | null | undefined, maxBytes = maxUploadBytes()): string | null {
  if (!file) return 'Choose a CSV file to upload.';
  const isCsv = file.name.toLowerCase().endsWith('.csv') || file.type === 'text/csv';
  if (!isCsv) return 'The file must be a CSV (.csv).';
  if (file.size > maxBytes) {
    return `The file is ${formatBytes(file.size)}; the limit is ${formatBytes(maxBytes)}.`;
  }
  return null;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
