# jettison/code-relevance — the model, and why it has to be ours

## The gap, established by testing rather than assumption

| Candidate | Verdict on a developer laptop |
|---|---|
| **SWE-Pruner** `code-pruner` (0.63B) | ❌ needs CUDA/flash-attn. MPS crashes on device placement; **CPU timed out after 10 minutes** on one 1,400-line file. |
| **Headroom** `kompress-v2-base` (ModernBERT, 150M) | ⚠️ runs fine (0.4s, ONNX, Apache-2.0) but is a **prose** compressor. On code it strips keywords — `from __future__ import annotations` becomes `__future__ annotations`. **Never route code through it.** |
| Jettison's current line scorer | regex; ~10ms; no notion of semantics |

**Nothing exists that scores code lines for relevance fast enough to sit
in a per-read hook.** That is the contribution: not "a code pruner" —
those exist — but one that runs where every Claude Code user actually is.

## Feasibility — settled by the literature

From the Elicit review of 80 papers on distilled code encoders:

- sub-200M distilled encoders retain **97–98%** of teacher accuracy on
  relevance ranking and line-level token classification
- **8–20ms** on developer CPUs; a 6MB ONNX-quantized completion model
  serves at **8ms per suggestion** in Visual Studio
- CodeBERT/GraphCodeBERT compress to **3MB** at 97–98% retention, 76x faster
- TinyBERT at **14.5M params** reaches 96.8% of BERT-Base, 9.4x faster
- **feature-based** distillation beats response-based: 98% of teacher at
  **5% of the parameters**
- PEFT/LoRA underperforms full fine-tuning on code *generation* but
  matches or exceeds it on code *understanding* — which is our task, so
  training stays cheap

## The trap, and why it is our advantage

> *Standard accuracy metrics systematically overstate the fidelity of
> compressed models.*

Distilled code models show up to **285% greater degradation** under
adversarial perturbation, **62% behavioral discrepancy** in prediction
agreement with their teacher, and are **4x less robust to metamorphic
variants** — including something as ordinary as renaming a variable.

A pruner that keeps the right lines until someone renames a parameter is
useless in production, and conventional evaluation would never reveal it.
Published mitigations: MoEKD (+35.8% adversarial robustness), MORPH (+47%
metamorphic robustness).

**Jettison already has the two things that catch this** — the commitment
verifier and a live A/B harness. Shipping metamorphic robustness numbers
beside accuracy is the differentiator, not an afterthought.

## Plan

| | |
|---|---|
| Student | ~84M (DistilVD-style 6-layer); stretch target TinyBERT scale |
| Base | `answerdotai/ModernBERT-base` (Apache-2.0), the base Kompress uses |
| Task | token classification → per-line relevance given a query |
| Method | **feature-based** distillation |
| Teacher | SWE-Pruner's 0.63B, one GPU rental to label |
| Data | SWE-Pruner's released 61k set + traces from real sessions |
| Validation | **metamorphic first**: rename identifiers, reorder functions, reformat. Accuracy alone is not evidence. |
| Export | ONNX — **benchmark before quantizing**; INT8 can *increase* latency on some hardware |
| Publish | `jettison/code-relevance`, lineage credited |

Legitimacy: training our own weights and naming them ours is exactly what
SWE-Pruner did (from Qwen3-Reranker) and Headroom did (from ModernBERT).
What is not legitimate is redistributing someone else's weights under a
new name, which we do not do.

## Do this only after

1. the composition A/B says the client-side stack is worth shipping, and
2. a check that no suitable distilled code encoder already exists.

Training is a few days plus modest GPU rental. Both prior steps are free
and either could make it unnecessary.
