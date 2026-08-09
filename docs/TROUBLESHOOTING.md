# Troubleshooting and error catalog

| Symptom/code | Meaning | Safe action |
|---|---|---|
| `Unsafe production configuration` | Production guard found HTTPS/secret/provider errors | Run `doctor`; correct environment values; do not bypass |
| `google_credentials_missing` | OAuth client file not configured/readable | Mount the correct web-client JSON outside the repo |
| `invalid_oauth_state` | Callback does not match the initiating session | Restart connection from the same logged-in browser |
| `proposal_not_sendable` | Proposal already sent/confirmed or wrong state | Reload; inspect audit; do not force duplicate send |
| `appointment_not_bookable` | Slot not confirmed, already booked, or concurrent claim | Reload and use existing Calendar link if booked |
| `manual_required` reminder | No template or ambiguous provider result | Verify provider state and handle once manually |
| Readiness 503 | Paused or provider/config incomplete | Operator readiness endpoint/Settings gives safe detail |
| Encrypted value says different key | `DATA_ENCRYPTION_KEY` changed | Restore prior key/backup; do not overwrite ciphertext |
| SQLite busy | Another worker/web write held lock too long | Ensure one worker, local volume, and no network filesystem |
| WhatsApp 4xx | Token, phone ID, policy, recipient, or template issue | Inspect Meta dashboard; fix account/config; no blind retry |
| Google 401/403 | OAuth revoked, scope/account/Calendar permission issue | Reconnect intended account and verify calendar ID |
