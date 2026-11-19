# Implementation references

Inspected 19 November 2026. The preceding project-selection research retained 48 primary sources. These are the specific references used for this implementation.

- [Baseten Loops quickstart](https://docs.baseten.co/loops/quickstart.md): model, serverless scope, group-centered rewards, CISPO data, sampling and cleanup.
- [SFT SDK example](https://docs.baseten.co/examples/sft-sdk-loop.md): masked/shifted supervised targets and optimizer updates.
- [ServiceClient](https://docs.baseten.co/reference/sdk/loops/service-client.md): run creation, explicit scope, standalone sampler and session-scoped cleanup.
- [TrainingClient](https://docs.baseten.co/reference/sdk/loops/training-client.md): state/weight checkpoints, optimizer, tokenizer and paired sampler.
- [SamplingClient](https://docs.baseten.co/reference/sdk/loops/sampling-client.md): token limits, seed, temperature, checkpoint pinning and timeout behavior.
- [Capabilities API](https://docs.baseten.co/reference/loops-api/server/get-capabilities.md): workspace enablement, serverless availability and sequence limits.
- [Serverless mode](https://docs.baseten.co/loops/availability-modes/serverless.md): fail instead of falling back to dedicated capacity.
- [Pricing](https://www.baseten.co/pricing/): inspected promotional token rates; recheck before running.
- [Billing enforcement](https://docs.baseten.co/organization/billing.md): account budgets do not enforce training/dedicated spend.
- [Qwen3.6 model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B): pretrained model architecture and license.
- [Cloudflare Durable Objects](https://developers.cloudflare.com/durable-objects/): state, concurrency and SQLite-backed objects.
- [Cloudflare R2](https://developers.cloudflare.com/r2/): object storage and Workers bindings.
- [Workers limits](https://developers.cloudflare.com/workers/platform/limits/): runtime limits.
- [SQLite authorizer](https://www.sqlite.org/c3ref/set_authorizer.html): SQL operation authorization.
- [Python SQLite](https://docs.python.org/3/library/sqlite3.html): URI read-only mode, progress handler and runtime limits.
- [Baseten Loops package 0.36.0](https://pypi.org/project/baseten-loops/0.36.0/): installed SDK signatures and models checked locally.

The installed SDK source was also inspected: queued submission retries reuse `Idempotency-Key`; futures expose `operation_id`. These facts support the application stopping on an unresolved outcome rather than initiating a fresh operation.
