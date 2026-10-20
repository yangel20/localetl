import type { ErrorCode, ErrorDetail } from './types';

/** Codes produced by the client itself, never by the API. */
export type ClientErrorCode = 'network_error' | 'invalid_response';

/** Any non-2xx response (parsed from the contract `Error` body) or a client-side transport failure. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode | ClientErrorCode;
  readonly details: ErrorDetail[];

  constructor(
    status: number,
    code: ErrorCode | ClientErrorCode,
    message: string,
    details: ErrorDetail[] = [],
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}
