# Final verification report - 1.0.0

Date: 2026-08-09

## Passed locally

- Python compilation and dependency consistency: passed.
- Automated suite: 37 passed, including concurrent SQLite send, confirmation, and rate-limit tests.
- Dependency vulnerability audit: no known vulnerabilities in the exact commit's two Linux CI runs and Windows package run.
- PowerShell syntax: all Windows launch/build/test scripts parsed successfully.
- Windows source runtime: installer, web/worker start, health response, resource readout, and exact-process stop passed.
- Windows packaged runtime: health 200, branded login 200, 65.5 MiB idle working set, and exact-process shutdown passed.
- Windows ZIP: 1,315 entries, CRC check clean, executable and README present.
- ZIP SHA-256: `08163085D541B8B83A71D3A2160B8A8E0F345B6B4106FF176955F7153458AAC7`.
- Docker: configuration valid; final hardened image built from a 249.13 KiB context with package artifacts excluded, ran as uid/gid 10001 `agenda`, returned health 200, and refused unsafe production configuration with exit code 1.
- Browser: desktop and mobile operator flows rendered and interacted successfully with no console warnings/errors.
- Performance: established 1,000-record baseline remains 601.5 records/second with 4.792 ms median dashboard reads. A final contention-heavy 500-record rerun measured 3.036 ms median, 4.799 ms p95, a 10.763 ms 500-item HAI page, and 0.64 MiB peak Python allocation.
- Repository truth scan: no private-key/token signatures or encoding corruption; runtime secrets/data/build outputs are ignored.
- Publication: hardened commit `21c6976` is pushed to draft PR #1 against `main`; both independent Linux CI checks passed on that exact SHA.
- Final Windows GitHub Actions package run `31288093704` passed in 1m33s. It ran all 37 tests, audited dependencies, built and launch-tested the executable, and uploaded the 33,136,022-byte `AgendaRelay-Windows-x64` artifact with GitHub digest `sha256:816349fa6fc2c15bf43731528b25a4b10ec1d250ccd1bd475c3a9a72f0332399`.

## Provider/account gate

No real WhatsApp message or Google Calendar event was created during release verification. A temporary isolated ngrok agent reached the cloud service, but the account's free endpoint was already online elsewhere and ngrok returned `ERR_NGROK_334`. Agenda Relay did not enable endpoint pooling or disturb that existing tunnel. Live production acceptance therefore still requires authorized Meta and Google credentials/approvals plus an assigned available ngrok domain/session.

This distinction is intentional: local build/test/package readiness is verified; real-provider production operation is not claimed without owner-authorized accounts and cleanup.
