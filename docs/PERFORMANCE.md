# Performance and resource profile

Agenda Relay is optimized for a single Windows operator and a moderate WhatsApp scheduling workload. SQLite uses one persistent connection per application thread, WAL journaling, a five-second busy timeout, bounded statement caching, a 4 MiB page cache, and indexed dashboard/feed queries. Static assets receive immutable caching while authenticated and dynamic responses remain `no-store`.

Measured on the development Windows 11 host on 2026-08-09:

| Workload | Result |
|---|---:|
| Create 1,000 contacts and scheduling requests with audits | 601.5 records/second |
| Dashboard query over 1,000 requests | 4.792 ms median; 12.036 ms p95 |
| HAI feed page of 500 items | 22.131 ms |
| Benchmark Python peak allocation | 0.66 MiB |
| Source web and worker idle working set | about 4-5 MiB per process |
| Packaged web-plus-worker executable idle working set | about 65 MiB |

Results are a repeatable local baseline, not a production capacity guarantee. Run the same bounded workload on the target machine with:

```powershell
python -m scripts.benchmark --records 1000 --reads 500
```

## Fresh local benchmark — 2026-09-23

The same bounded command was rerun on the Windows 11 development host:

| Workload | Result |
|---|---:|
| Create 1,000 contacts and scheduling requests with audits | 3,118.9 records/second |
| Dashboard query over 1,000 requests | 1.342 ms median; 2.262 ms p95; 3.602 ms maximum |
| HAI feed page of 500 items | 5.265 ms |
| Benchmark Python peak allocation | 0.69 MiB |

This is a dated local observation from one run, not a production capacity guarantee. It is not directly comparable to the 2026-08-09 baseline as a promise of a fixed speedup; hardware load, cache state, and measurement variability can affect the result. Re-run the command on the intended deployment machine before capacity planning.

## Benchmark methodology correction — 2026-10-13

The original benchmark enabled `tracemalloc` during the timed write, dashboard-read, and feed workloads. Allocation tracing adds runtime overhead, so those timings were instrumented and should be treated as historical rather than directly comparable to uninstrumented application performance. The benchmark now runs the timed pass without tracing and repeats the workload separately for Python allocation measurement. The allocation figure excludes native SQLite memory and is not process working set.

Three consecutive runs of `python -m scripts.benchmark --records 1000 --reads 500` on this Windows 11 host produced:

| Workload | Observed range |
|---|---:|
| Create 1,000 contacts and requests | 874–1,171 records/second |
| Dashboard query median | 0.554–1.113 ms |
| Dashboard query p95 | 0.593–1.769 ms |
| HAI feed page of 500 items | 4.551–7.680 ms |
| Traced Python peak allocation | 0.48 MiB in each run |

Write throughput and tail latency vary across repeat runs on the same host, which is why the table reports a range and not a performance guarantee. Re-run on the deployment machine under representative load before sizing or making latency commitments.

An additional three serial runs on 2026-10-13 produced 134–564 writes/second, 0.593–0.664 ms dashboard median, 0.777–1.289 ms dashboard p95, 4.720–6.608 ms for a 500-item HAI page, and 0.48 MiB traced Python peak. The large write-throughput spread versus the earlier sample is a reason to profile under controlled, representative host load before drawing a capacity conclusion; do not treat either sample as a stable throughput guarantee. The benchmark database is temporary and does not touch the operator's configured database.

The first three serial runs on 2026-10-14 with the same command on Windows 11 produced:

| Workload | Observed range |
|---|---:|
| Create 1,000 contacts and requests | 230.6–773.9 records/second |
| Dashboard query median | 0.660–1.344 ms |
| Dashboard query p95 | 1.154–2.039 ms |
| HAI feed page of 500 items | 4.755–10.514 ms |
| Traced Python peak allocation | 0.49 MiB in each run |

These temporary-database runs were serial and verified 1,000 records each. The write-throughput spread remains too large to support a reliable before/after optimization claim; no write-path optimization was promoted from this sample. Profile on a controlled, representative deployment host before tuning persistence.

An additional three serial runs later on 2026-10-14 produced:

| Workload | Observed range |
|---|---:|
| Create 1,000 contacts and requests | 388.1–782.2 records/second |
| Dashboard query median | 0.735–1.331 ms |
| Dashboard query p95 | 1.377–1.773 ms |
| HAI feed page of 500 items | 4.339–7.911 ms |
| Traced Python peak allocation | 0.49 MiB in each run |

Across both same-day samples (six serial runs), the combined ranges were 230.6–782.2 records/second, 0.660–1.344 ms dashboard median, 1.154–2.039 ms p95, 4.339–10.514 ms for the 500-item HAI page, and 0.49 MiB traced Python peak. Each run verified 1,000 records and used a temporary database. The spread still does not support a reliable optimization claim; no write-path change was promoted.

The structured run artifact at `.ecc/benchmarks/sqlite-workload-2026-10-13.json` records another three-run sample against commit `6eb14af`. It observed 993–1,149 records/second, 0.551–0.584 ms dashboard median, 0.638–0.806 ms dashboard p95, 3.655–4.852 ms for a 500-item HAI page, and 0.48 MiB traced Python peak. These are local synthetic results only; concurrent load, cold cache, and real provider latency remain unmeasured.

## Larger synthetic dataset — 2026-10-14

One run of `python -m scripts.benchmark --records 10000 --reads 1000` on the same Windows 11 host verified all 10,000 records and observed 703.7 writes/second, dashboard reads at 10.771 ms median / 13.652 ms p95 / 120.894 ms maximum, a 6.674 ms HAI page of 500 items, and 0.49 MiB traced Python peak allocation. The workload uses a disposable local database and one process; the memory figure excludes native SQLite allocations. This is a single synthetic sample, not a latency or capacity guarantee. The elevated maximum alongside a much lower p95 should be treated as host/workload variance until repeated under controlled conditions. The benchmark supports keeping bounded pagination and existing indexes; it does not justify a persistence rewrite or a claim about concurrent users.

Calendar availability uses one Google FreeBusy query for the full 21-day search window and filters returned busy ranges against local business hours. In the regression scenario with two weeks of full weekdays, this reduced the provider-call count from 11 per-day queries to one batched query. Booking still performs a separate final availability check before event insertion. The call-count result is a deterministic test, not a live Google latency benchmark.

The executable's larger idle footprint comes from bundled Python and provider libraries. For horizontal scaling, multiple operators, or sustained write concurrency, move persistence and rate/job coordination to PostgreSQL rather than sharing the SQLite file across machines.
