"""Outbound events and webhooks (VRT-28, ADR-0005): a transactional outbox,
fan-out into per-endpoint deliveries, and delivery signed per the Standard
Webhooks spec with retries over ~3 days."""
