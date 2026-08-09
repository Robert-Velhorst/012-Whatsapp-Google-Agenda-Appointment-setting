# Task graph

```text
Repository/PDF audit
  -> configuration + secret boundary
  -> migrations + ownership + encryption
  -> signed inbound webhook
      -> deterministic intent
      -> Google FreeBusy
      -> proposal review
          -> WhatsApp send
          -> contact confirmation (reply or private link)
              -> appointment review
              -> Google event insert
                  -> WhatsApp confirmation
                  -> reminder job
                      -> approved template send OR manual_required
  -> audit/privacy/retention
  -> operator dashboard + auth/CSRF
  -> CLI/backup/doctor/support bundle
  -> Docker/CI/docs
  -> automated tests
  -> browser QA
  -> real-provider acceptance (external gate)
```

External dependency order: public HTTPS -> Meta callback approval and Google redirect registration -> OAuth/Cloud API credentials -> consented critical-path rehearsal -> approved reminder template.
