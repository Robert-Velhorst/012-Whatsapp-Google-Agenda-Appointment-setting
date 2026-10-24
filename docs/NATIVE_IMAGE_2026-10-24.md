# Native container runtime qualification

This separate draft preserves dependency/runtime candidate #22 at
`3dc7ffc284e37081861f98710087a667a7852c3b`. The original source and Windows
free-threaded package gates remain in place. No operator database migration
or real Google/Meta operation is authorized by building this image.

## Selected native image

- Digest-pinned Python 3.15.1 and Rust 1.99.1 Alpine 3.24 SDK images.
- Checksum-verified upstream SQLite 3.54.1 and OpenSSL 4.1.0 source, built only
  in a fresh `/native-build` SDK with `/opt/agenda-native` as the dedicated prefix.
- CPython `_ssl` and `_hashlib` compiled from the exact 3.15.1 source and
  cryptography 50.0.2 built from its hash-locked source against OpenSSL 4.1.0.
- Hash-locked native build requirements; locally built wheels are hashed again
  and installed offline. Build SDKs and package installers are absent from the
  final application environment.
- SQLite and OpenSSL runtime APKs carry source/license/provenance and inventory
  records. Signing keys are ephemeral builder inputs and never exported.
- Preserve username `agenda`, UID 10001, `/app/data`, standard SQLite API,
  Waitress entry point, paused-worker and image health contracts.

The build and inspector scripts are adapted from reviewed MCP Hub source
`3ed125e157ed23d3254a7a91b2409893566d811e`. Each guard, source checksum, ABI,
library mapping, wheel inventory, usable CA-root and legacy-provider check is
retained with this repository's prefix and paths. Compatibility OpenSSL 3
packages may still exist in the distribution; installed and loaded libraries
are reported separately. This does not claim every native component latest.

## Qualification evidence required

CI preserves the existing source suite, Windows package suite and isolated
no-network production-image smoke. It additionally records installed versions,
library hashes/maps, source provenance, UID and complete OS/Python inventory.
The exact inspected image is saved and its descriptor/configuration bytes
verified before scanning. Trivy 0.76.1 retains every package and all raw findings;
any vulnerability or modified-finding record fails qualification. No ignorefile,
advisory exemption or hidden severity filter is used. Artifacts are retained
even when qualification fails.

Local preparation checks cover Python AST, JSON/YAML, whitespace and unchanged
application cases/lock inputs only. No local app suite, native compilation,
host SDK install, operator data opening, provider call or deployment occurred.
Actual image construction, existing case results and unsuppressed scan outcome
remain unproven until their exact-head hosted evidence is reconciled.

## Official sources

- [Python 3.15.1](https://www.python.org/downloads/release/python-3151/)
- [OpenSSL 4.1.0](https://github.com/openssl/openssl/releases/tag/openssl-4.1.0)
- [SQLite source checksums](https://www.sqlite.org/download.html)
- [Trivy 0.76.1](https://github.com/aquasecurity/trivy/releases/tag/v0.76.1)
- [Rust stable manifest](https://static.rust-lang.org/dist/channel-rust-stable.toml)
- [Alpine releases](https://www.alpinelinux.org/releases/)
