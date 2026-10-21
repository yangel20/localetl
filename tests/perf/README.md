# Performance check (REQ-61)

A 1,000,000-row x 10-column CSV (about 100 MB) must complete a `replace` run in under 5 minutes,
and memory must stay bounded to about one chunk (it must not grow with file size).

The test is opt-in because it takes minutes:

```sh
LOCALETL_PERF=1 TEST_DATABASE_URL=postgresql+psycopg://localetl:localetl@127.0.0.1:5432/localetl_test \
  python -m pytest tests/perf -s
```

* `LOCALETL_PERF_ROWS` (default 1000000) changes the size; the 5-minute limit applies only at 1M rows or more.
* `LOCALETL_PERF_DIR` chooses where the generated CSV goes (default: pytest's temp directory, outside
  the repository). The data is generated at run time and never committed.
* Each run happens in a child process (`child.py`) against a throwaway database, so peak RSS
  (`ru_maxrss`) is measured per run. Memory is checked by running a small file (200,000 rows) and the
  full file and requiring that the full run needs only a small constant extra amount of memory.
* Results (seconds, rows/s, peak MB) are printed and written to `perf-result.json` in the temp dir.
