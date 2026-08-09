# Release verification - 1.0.0

Date: 2026-08-09

## Passed locally

- Python compilation and dependency consistency: passed.
- Automated suite: 25 passed.
- Dependency vulnerability audit: no known vulnerabilities.
- PowerShell syntax: all Windows launch/build/test scripts parsed successfully.
- Windows source runtime: installer, web/worker start, health response, resource readout, and exact-process stop passed.
- Windows packaged runtime: health 200, branded login 200, 65.5 MiB idle working set, and exact-process shutdown passed.
- Windows ZIP: 1,315 entries, CRC check clean, executable and README present.
- ZIP SHA-256: `08163085D541B8B83A71D3A2160B8A8E0F345B6B4106FF176955F7153458AAC7`.
- Docker: configuration valid; final image built with a 45.28 KiB context after excluding 181 MiB of package artifacts, ran as uid/gid 10001 `agenda`, returned health 200, and refused unsafe production configuration with exit code 1.
- Browser: desktop and mobile operator flows rendered and interacted successfully with no console warnings/errors.
- Performance: 1,000 scheduling records at 601.5 records/second; dashboard median 4.792 ms and p95 12.036 ms; 500-item HAI page 22.131 ms.
- Repository truth scan: no private-key/token signatures or encoding corruption; runtime secrets/data/build outputs are ignored.
- Publication: fresh remote clone at commit `650cccf` passed 25 tests; both GitHub CI checks passed; draft PR #1 opened against `main`.

## Provider/account gate

No real WhatsApp message or Google Calendar event was created during release verification. A temporary isolated ngrok agent reached the cloud service, but the account's free endpoint was already online elsewhere and ngrok returned `ERR_NGROK_334`. Agenda Relay did not enable endpoint pooling or disturb that existing tunnel. Live production acceptance therefore still requires authorized Meta and Google credentials/approvals plus an assigned available ngrok domain/session.

This distinction is intentional: local build/test/package readiness is verified; real-provider production operation is not claimed without owner-authorized accounts and cleanup.
