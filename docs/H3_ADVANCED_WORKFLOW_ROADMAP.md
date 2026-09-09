# H3 Advanced Workflow Roadmap

## Product-layer rule

Advanced workflows are versioned additions. `GOLDEN_V1_PRODUCTION_BASELINE`
remains immutable and available as the production fallback. Advanced work must
reuse the existing Studio Job truth, native Comfy handoff, support-layer
provenance, and managed output contracts. It must not create a second engine or
second project/job state model.

## Capability families

| Family | NOW | NEXT | LATER | EXPERIMENTAL |
|---|---|---|---|---|
| Architecture fidelity | Baseline rubric, façade/edge/material constraints in V2 prompt profile | Controlled geometry-preservation experiments and objective frame review | Structural consistency across longer clips | New conditioning or specialized nodes only after provenance review |
| Camera control | Semantic slow push/orbit language where H3 accepts prompt conditioning | Compare camera-language presets with fixed graph parameters | Native path controls if a verified H3 input contract appears | External camera-control nodes pending compatibility proof |
| Reference preservation | First-frame identity and subject-lock constraints | Multi-seed adherence comparison | Multi-reference hierarchy | New reference-conditioning nodes |
| Quality profiles | Standard inherited Golden profile | Preview vs standard parameter study | High-quality / high-resolution production profiles | Hardware-specific experimental profiles |
| Multi-reference / direction | Document capability gap | Define reference priority contract | Separate material/style references | New multi-reference conditioning |
| Long-motion continuity | Short-clip rubric | Segment/stitch evaluation design | Longer duration and temporal stability | New temporal modules |
| Prompt / workflow coordination | Advanced semantic profile | Workflow-aware camera presets | Architecture-specific grammar and negative constraints | Automatic workflow synthesis |

## Current A1 prototype

`06_Advanced_Architecture_Camera_V2` is the first isolated prototype. It keeps
the 04 Golden model, sampler, scheduler, VAE pair, resolution, frame rate,
steps, seed, and graph topology unchanged. Its only execution-affecting
experiment is a stronger architecture-camera conditioning profile: controlled
slow movement, subject lock, façade/material preservation, stable horizon, and
explicit no-morph/no-addition constraints. Output identity is changed only so
results cannot be confused with Golden output.

The installed node inventory includes the proven H3, Comfy core, and
VideoHelperSuite surfaces. Although the runtime exposes other camera-related
nodes, none is currently an input of `MiniMaxH3ImageToVideo`; they are not
connected as placebo controls. New external custom-node repositories are an
optional future candidate, not an A1 dependency.

## Gates before promotion

1. Static API/UI parity, link integrity, both VAE paths, node availability, and
   deterministic SHA.
2. Owner-authorized single B-arm GPU run, reusing an existing comparable Golden
   output where possible.
3. Objective metadata and visual A/B rubric: geometry preservation, reference
   fidelity, camera smoothness, material stability, temporal stability,
   architectural hallucination, and overall quality, each scored 1–5.
4. Explicit decision: `V2_PROMISING`, `V2_NEEDS_ITERATION`, or `V2_REJECTED`.

No A1 prototype is promoted to the production selector automatically.
