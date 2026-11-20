# Hardware preflight: prepared, submission rejected

Checked on 20 November 2026. **No new GPU job was created and no new training was performed.**

The follow-up must record actual hardware before measured work. The new `hardware_probe.py` captures physical GPU name/UUID/count/VRAM, MIG state, driver version, Python/PyTorch/CUDA/cuDNN versions, and a small CUDA execution check. It rejects missing evidence, a different GPU, multiple GPUs, MIG partitions, insufficient memory, or disagreement between PyTorch and `nvidia-smi`. Four local tests cover the acceptance and rejection paths; the actual GPU probe has not run.

## Submission result

The authenticated `GET /v1/training_projects` request succeeded. The subsequent attempt to create the dedicated probe's project returned:

```json
{
  "http_status": 403,
  "body": {
    "code": "PERMISSION_DENIED",
    "message": "You are not authorized for Baseten training."
  }
}
```

Project creation failed before the job submission endpoint was called. This proves that the current credentials cannot create the Training Jobs project through this endpoint. The error does not distinguish a missing workspace entitlement from a credential permission or team-specific requirement. Provider clarification is required; adding a payment method alone is not established as a sufficient fix.

The separate Loops capabilities request still reports the original model enabled for serverless operation. That does not establish Training Jobs authorization.

## Price and scope

The billing dashboard displayed **$0.29 in rounded usage**, including $0.18 for the original run and $0.11 for the standalone base sampler. No invoice was issued, and the dashboard reported no payment method. These are observed dashboard amounts, not an invoice or a guarantee that every outstanding charge has settled.

The prepared probe requests one H100 on one node. The public training price was **$0.10833 per minute**, approximately $6.50/hour. Its planning reservation is $2 within the proposed $10 new-compute envelope. The in-container process is limited to 90 seconds; its local controller requests termination ten minutes after submission, including provisioning. Provider API availability is needed for controller termination; this is not a provider-enforced dollar cap.

The catalog's separate, ready-made inference deployment for Qwen3.6-35B-A3B suggests **4 H100s, 320 GiB total, $0.4333/minute**. This is an inference configuration, not a quote for a Loops trainer and not proof of the old serverless hardware. The workspace also reports that its Baseten Inference Stack access is not enabled.

## Reproduction

Prepare the exact request locally without making any API calls:

```bash
python study/launch_hardware_probe.py --out runs/hardware-request
python -m unittest discover -s study -p 'test_hardware_probe.py' -v
```

After resolving access and rechecking prices/budget, the explicitly billable command is:

```bash
python study/launch_hardware_probe.py --out runs/hardware-attempt --submit
```

It reads `BASETEN_API_KEY` from the local environment and does not inject that credential into the GPU container. It creates neither an interactive session nor an inference endpoint.

This is an infrastructure probe, **not the executor for the 1,680-episode prospective study**. A successful probe on one allocation must not be used to attribute hardware to a later allocation. Run the check again inside each measured job before model work. Memory fit, exact training behavior, adapter checks, and the paired multi-seed execution adapter still need validation before the prospective experiment.

References: [Training Jobs quickstart](https://docs.baseten.co/training/getting-started), [Training API](https://docs.baseten.co/reference/training-api/create-training-project), [pricing](https://www.baseten.co/pricing/), and [billing](https://docs.baseten.co/organization/billing).
