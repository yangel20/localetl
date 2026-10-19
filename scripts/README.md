# scripts/

| Script | Purpose |
|---|---|
| `dev-up.sh [timeout]` | `docker compose up -d db`, then wait until the healthcheck reports healthy (default 60 s). |
| `db/init.sql` | Mounted into the Postgres init directory; creates `localetl_test`. |

## Database stack

```bash
cp .env.example .env          # optional; compose defaults equal .env.example
scripts/dev-up.sh             # or: docker compose up -d db
docker compose down           # stop, keep data
docker compose down -v        # stop and DELETE the volume (full reset)
```

- PostgreSQL 16 on `127.0.0.1:5432` only (not exposed to the network). If a local Postgres already uses 5432, set `POSTGRES_PORT=55432` (compose-only override) and point `DATABASE_URL`/`TEST_DATABASE_URL` at that port.
- Databases: `localetl` (from `POSTGRES_DB`) and `localetl_test` (from `init.sql`).
- User/password come from `POSTGRES_USER` / `POSTGRES_PASSWORD`.
- Data lives in the named volume `localetl_pgdata`.
- `init.sql` runs **only on first initialisation of an empty volume**. If you
  changed it or the credentials, run `docker compose down -v` and start again.
- `localetl_test` is for pytest (`TEST_DATABASE_URL`) and may be wiped by tests.
