/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  /** Client-side upload limit in MB; defaults to 100 (LOCALETL_MAX_UPLOAD_MB's default). */
  readonly VITE_MAX_UPLOAD_MB?: string;
}
