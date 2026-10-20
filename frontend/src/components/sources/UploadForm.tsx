import { useState, type FormEvent } from 'react';
import { api } from '../../app/api/client';
import { ApiError } from '../../app/api/errors';
import type { CsvOptions, DataSource } from '../../app/api/types';
import { ErrorMessage } from '../ErrorMessage';
import { checkUploadFile } from './uploadRules';

const ENCODINGS: CsvOptions['encoding'][] = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252'];
const DELIMITERS: { value: CsvOptions['delimiter']; label: string }[] = [
  { value: ',', label: 'Comma (,)' },
  { value: ';', label: 'Semicolon (;)' },
  { value: '\t', label: 'Tab' },
  { value: '|', label: 'Pipe (|)' },
];

const field = 'rounded border border-border bg-surface px-2 py-1';

export function UploadForm({ onUploaded }: { onUploaded: (source: DataSource) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [encoding, setEncoding] = useState<CsvOptions['encoding']>('utf-8');
  const [delimiter, setDelimiter] = useState<CsvOptions['delimiter']>(',');
  const [hasHeader, setHasHeader] = useState(true);
  const [quoteChar, setQuoteChar] = useState('"');
  const [clientError, setClientError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setApiError(null);
    const problem = checkUploadFile(file) ?? (quoteChar.length !== 1 ? 'The quote character must be exactly one character.' : null);
    setClientError(problem);
    if (problem || !file) return;
    setBusy(true);
    try {
      const source = await api.createSource(file, {
        name: name.trim() || undefined,
        encoding,
        delimiter,
        has_header: hasHeader,
        quote_char: quoteChar,
      });
      onUploaded(source);
    } catch (err) {
      setApiError(err instanceof ApiError ? err : new ApiError(0, 'network_error', 'Upload failed'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded border border-border bg-surface-muted p-4" aria-label="Upload CSV">
      <h2 className="text-lg font-semibold">Upload a CSV</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm sm:col-span-2">
          CSV file
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setClientError(null);
            }}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm sm:col-span-2">
          Name (optional)
          <input className={field} value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Encoding
          <select className={field} value={encoding} onChange={(e) => setEncoding(e.target.value as CsvOptions['encoding'])}>
            {ENCODINGS.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Delimiter
          <select className={field} value={delimiter} onChange={(e) => setDelimiter(e.target.value as CsvOptions['delimiter'])}>
            {DELIMITERS.map((d) => (
              <option key={d.label} value={d.value}>{d.label}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Quote character
          <input className={field} value={quoteChar} maxLength={1} onChange={(e) => setQuoteChar(e.target.value)} />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={hasHeader} onChange={(e) => setHasHeader(e.target.checked)} />
          First row is a header
        </label>
      </div>
      {clientError && (
        <p role="alert" className="text-sm text-danger">{clientError}</p>
      )}
      {apiError && <ErrorMessage error={apiError} />}
      <button
        type="submit"
        disabled={busy}
        className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-fg disabled:opacity-60"
      >
        {busy ? 'Uploading…' : 'Upload'}
      </button>
    </form>
  );
}
