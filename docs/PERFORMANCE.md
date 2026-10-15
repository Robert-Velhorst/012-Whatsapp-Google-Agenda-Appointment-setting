# Performance and resource profile

Agenda Relay is optimized for a single Windows operator and a moderate WhatsApp scheduling workload. SQLite uses one persistent connection per application thread, WAL journaling, a five-second busy timeout, bounded statement caching, a 4 MiB page cache, and indexed dashboard/feed queries. Per-thread connection teardown does not run `PRAGMA optimize`, which can contend for SQLite write locks when worker threads shut down concurrently; schema statistics are not required for the indexed bounded queries. Static assets receive immutable caching while authenticated and dynamic responses remain `no-store`.

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

Three additional serial 10,000-record runs on 2026-10-14, after the dependency refresh, verified all records and observed 456.1–867.4 writes/second, 6.436–6.695 ms dashboard median, 8.315–9.884 ms p95, 39.844–118.181 ms maximum, 4.739–5.317 ms for the 500-item HAI feed, and 0.49 MiB traced Python peak in each run. Exact values are recorded in `.ecc/benchmarks/sqlite-workload-10000-2026-10-14.json`. Median and p95 were relatively stable, but maxima and write throughput varied materially; this does not isolate the outliers to the application or justify a resource/performance tradeoff. The runs use separate temporary databases and are not a concurrent-load, cold-cache, production, or Hetzner benchmark.

Calendar availability uses one Google FreeBusy query for the full 21-day search window and filters returned busy ranges against local business hours. In the regression scenario with two weeks of full weekdays, this reduced the provider-call count from 11 per-day queries to one batched query. Booking still performs a separate final availability check before event insertion. The call-count result is a deterministic test, not a live Google latency benchmark.

The executable's larger idle footprint comes from bundled Python and provider libraries. For horizontal scaling, multiple operators, or sustained write concurrency, move persistence and rate/job coordination to PostgreSQL rather than sharing the SQLite file across machines.

## Atomic contact/request write — 2026-10-14

For automatic webhooks, the contact is still committed before intent classification to preserve the existing failure boundary. Once a scheduling intent is known, the subsequent contact-language update, request insert, and `request.detected` audit now commit atomically instead of using two transactions. The personal-assisted path and 1,000-record synthetic benchmark atomically create contact/request/audit together. The benchmark's logical data and correctness gate are unchanged. An interleaved A/B comparison measured the prior two-transaction contact/request path at 66.7–120.3 records/second and the combined path at 34.1–138.5 records/second. Those ranges overlap widely, so this host sample does not establish a throughput improvement. The deterministic structural result is one commit per contact/request pair instead of two; a webhook regression asserts four total commits for inbound persistence, initial contact, contact-language/request/audit, and proposal creation. Keep this as a write-count and atomicity improvement, not a latency guarantee, and repeat measurements on a quiet representative host before capacity claims.

## Atomic request/audit write follow-up — 2026-10-14

Profiling found that request creation committed its scheduling row and its `request.detected` audit row separately. Request creation now inserts both in one transaction; an injected audit failure proves both rows roll back together. This also removes one SQLite commit per request.

Three serial 1,000-record runs before the change measured 143.9–198.3 records/second (median 164.4); three after measured 452.5–849.8 records/second (median 684.0). A 500-record/two-pass cProfile run counted 3,222 commit calls before and 2,222 after, a 31% reduction. The observed throughput median increased about 4.2×, but the sample is small and host throughput remains variable; treat the commit-count reduction as the direct structural result and do not use the throughput figure as a capacity guarantee. Dashboard median reads stayed within 0.657–1.176 ms across samples, the 500-item HAI feed within 5.061–7.777 ms, and traced Python peak stayed at 0.49 MiB. Full run values and limitations are in `.ecc/benchmarks/sqlite-request-audit-atomicity-2026-10-14.json`.

## Post-dependency-refresh sample — 2026-10-14

Three serial runs of the same temporary-database workload on the Windows 11 development host, after installing the current `requirements.lock`, verified 1,000 records each and observed 838.9–934.5 writes/second, dashboard medians of 0.585–1.051 ms, p95 of 0.693–1.491 ms, a 500-item HAI page in 4.701–9.065 ms, and 0.49 MiB traced Python peak. The structured runs are recorded in `.ecc/benchmarks/sqlite-workload-2026-10-14.json` against code commit `2fad193d4dd4aeeb9e595376e87fb490204f3107`. This is a single-host, serial synthetic sample; do not interpret it as concurrent capacity, live-provider latency, a stable speed claim, or a Hetzner benchmark. The workload uses temporary SQLite databases only.

## Fresh sample — 2026-10-15

Three serial runs of `python -m scripts.benchmark --records 1000 --reads 500` against the current working tree verified 1,000 records per run and observed 44.3–353.8 writes/second, dashboard medians of 0.630–0.917 ms, p95 of 0.928–1.968 ms, maximum reads of 5.174–7.372 ms, a 500-item HAI page in 1.857–3.192 ms, and 0.49 MiB traced Python peak. Dashboard/feed timings and Python allocation remained small, but write-throughput variation was too large to support a speedup or capacity claim. The runs used separate temporary databases on one Windows 11 host, serially; concurrent, cold-cache, live-provider, and Hetzner performance remain unmeasured.
