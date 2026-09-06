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

The executable's larger idle footprint comes from bundled Python and provider libraries. For horizontal scaling, multiple operators, or sustained write concurrency, move persistence and rate/job coordination to PostgreSQL rather than sharing the SQLite file across machines.
