import type { RunStatus } from '../../app/api/types';
import { STATUS_CLASS, STATUS_LABEL } from './runStatus';

/** Status is always conveyed by text, never by colour alone. */
export function StatusBadge({ status }: { status: RunStatus }) {
  return <span className={`font-medium ${STATUS_CLASS[status]}`}>{STATUS_LABEL[status]}</span>;
}
