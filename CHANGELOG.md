# Changelog

## 1.1.1 - 2026-10-21

- Setup sessions now carry `setup_token`: the single-use token for one add-card page, safe in a browser and never your API key. Pass it to asvri.js as `Asvri.mountCardSetup("#card", { setupToken: session.setup_token })`. `client_secret` is still returned with the same value but is deprecated. Guide: https://www.asvri.com/developers/cards-on-file

## 1.1.0 - 2026-10-20

- Cards on file: `asvri.setup_sessions` (create, retrieve, list, cancel), `asvri.payment_methods` (retrieve, list, detach) and `asvri.charges` (create, retrieve, list), on the sync and the async client. A charge is retried only when it has an idempotency key; without one it is never retried, so nothing is charged twice.
- Webhook event types `payment_method.attached`, `payment_method.detached`, `charge.succeeded`, `charge.failed` and `charge.requires_action`.

## 1.0.0 - 2026-10-19

- First release: checkout sessions, refunds, webhook endpoints and webhook signature checks.
