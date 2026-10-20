# Changelog

## 1.1.0 - 2026-10-20

- Cards on file: `asvri.setup_sessions` (create, retrieve, list, cancel), `asvri.payment_methods` (retrieve, list, detach) and `asvri.charges` (create, retrieve, list), on the sync and the async client. A charge is retried only when it has an idempotency key; without one it is never retried, so nothing is charged twice.
- Webhook event types `payment_method.attached`, `payment_method.detached`, `charge.succeeded`, `charge.failed` and `charge.requires_action`.

## 1.0.0 - 2026-10-19

- First release: checkout sessions, refunds, webhook endpoints and webhook signature checks.
