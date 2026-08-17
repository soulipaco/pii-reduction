# ADR-0015: CPU-only is a hard constraint; no component may require a GPU

**Status:** accepted · **Date:** 2026-08-18 · **Session:** 3

## Context

This repository is not only a portfolio artifact — the same design is being built in
parallel for real use, and the intended deployment target has no GPU clusters and no
plan to acquire any. Until now the constraint was implicit: the shipped stack happens
to be CPU-only, so nothing forced the question.

It stops being implicit as soon as transformer providers are considered. Databricks'
own `dbxredact` accelerator (reviewed session 3) ships six cluster profiles, three CPU
and three GPU, and states that "GLiNER models perform better on GPU, but other models
do not". That is the shape of the trap: a provider is added because it scores well on
a GPU profile, and the deployment target then needs hardware it will not have.

## Decision

**No component may require a GPU to function.** Concretely:

- Every provider must be usable on CPU. A provider whose only practical mode is GPU
  inference is rejected, not deferred.
- A provider that *benefits* from a GPU is acceptable if its CPU path is a supported
  configuration with measured throughput on the committed corpus, and its
  documentation in `docs/15_PROVIDERS.md` reports both.
- Benchmark results published as the project's baseline are CPU results. A GPU number
  may be reported beside one, never instead of one.
- No dependency may pull in CUDA/ROCm runtimes as a required install. GPU-only extras
  are not added.
- Roadmap Phase 7's transformer and GLiNER providers inherit this: they are evaluated
  on CPU latency and throughput as a first-class criterion, alongside quality. A model
  that is accurate but unusable on CPU at the corpus sizes this project targets does
  not qualify as a baseline candidate.

This constrains the answer to the open Greek PERSON gap (0.000–0.222 recall,
ADR-0007). Whatever eventually closes it must be CPU-viable; "run a large multilingual
transformer" is not automatically available as the answer.

## Consequences

- The current stack already complies: `phonenumbers`, spaCy `md`/`sm` models and
  Presidio are all CPU-only, and the measured Increment B baseline is a CPU result.
- Phase 7 provider evaluation gains a mandatory dimension: CPU latency and throughput,
  not only quality. `docs/08_EVALUATION_BENCHMARKING.md` already lists runtime quality
  as an evaluation level; this makes it a gate rather than a nice-to-have.
- Model-size choices tilt toward `md`/`sm` and quantized or distilled variants. The
  `lg` spaCy models remain acceptable — they are CPU models — but their load time and
  memory are now a reported cost.
- If a GPU-only approach ever becomes genuinely necessary, this ADR is superseded
  explicitly rather than eroded by one provider at a time.
