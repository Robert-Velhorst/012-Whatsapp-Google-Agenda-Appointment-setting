# October 23, 2026 stable dependency and SQLite refresh

## Public stable inventory

All 15 direct runtime/test/build declarations were compared with official PyPI latest metadata. python-dateutil moves from 2.9.0.post0 to 3.0.0. All 50 distinct packages represented by the runtime, development and packaging locks were independently compared with public stable releases; none were behind at the check time. The regenerated locks include distribution hashes and are installed with `--require-hashes`.

Python targets 3.15.1. The Windows CI target retains the existing free-threaded build; the normal CPython build remains supported for source operation at the same patch level. An older environment is preserved and rejected rather than silently overwritten. The existing Python-only draft #21 remains independent.

## Actual SQLite engine

[SQLite 3.54.1](https://www.sqlite.org/download.html) is the current database target. The inspected CPython 3.15.1 interpreter contains SQLite 3.53.1, so a Python version update alone is insufficient. This refresh keeps the standard `sqlite3` API, preserving its cursor, transaction, migration, backup and encryption-rotation behavior.

`tools/prepare_sqlite_runtime.py` downloads only pinned official SQLite archives and checks their published SHA3-256 before using their contents. On Windows x64 it creates a private copy of the selected CPython standard runtime, excluding user site packages and custom startup files, and replaces only that new copy's SQLite DLL. It never changes a shared interpreter. Its fresh child-process probe verifies actual Python/SQLite versions and the selected free-threaded build identity before a venv is created.

On Linux it compiles the pinned SQLite amalgamation into an owned library directory. Source launchers and CI use that directory through `LD_LIBRARY_PATH`; the Docker image contains the same library. A fresh process verifies the engine in every preparation path. No alternative binding or application schema migration is introduced. Store startup rejects an older engine before creating or opening its database path.

## Source operation

Use CPython 3.15.1 and a C compiler for Linux source setup: `make install PYTHON_EXECUTABLE=python3.15`, then `make run`, `make worker`, or `make test` with the same interpreter selection. The fixed command launcher supplies the prepared library path. Do not launch a stock interpreter directly against real data unless its actual SQLite engine meets the baseline.

On Windows, use `windows/Install-AgendaRelay.ps1`; `-PythonExecutable` can select an explicit CPython 3.15.1 installation. It prepares an isolated runtime and hash-enforced environment, preserving an existing incompatible venv. Normal setup retains its existing secure password prompt and credential generation behavior.

## Verification and deployment boundaries

Local tests cover the application on actual SQLite 3.54.1, including critical booking/audit atomicity, migrations, encryption, retention and concurrency. The added fixture creates data with the original older engine in a separate process, closes it, then reads/writes and backs it up with the current engine. Existing migration and database validation controls are retained.

Hosted CI must independently prove Linux native-library loading, Windows free-threaded source tests, the actual frozen executable's Python/SQLite identity, key rotation and backup operations, and the no-network container/paused-worker fixture. A successful package build alone is insufficient. No real Meta or Google provider acceptance is inferred from fixtures.

Hetzner remains the production target under `DEPLOYMENT_TARGET.md` and `docs/HETZNER_DEPLOYMENT.md`. Preserve and verify encrypted backups, stop writes for cutover, test restoration and rollback on a copy, and verify OAuth, TLS/proxy and provider behavior before deploying. No real operator database, service, credentials or deployment is changed by this draft. Distribution package updates and a dependency audit do not constitute a complete image vulnerability scan or prove every native OS component is the highest upstream version.
