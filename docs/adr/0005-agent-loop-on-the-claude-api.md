# ADR 0005: A hand-written agent loop on the Claude API, with a structured final answer

**Status:** Accepted · **Date:** 2026-10-18

## Context

The investigator needs an LLM that can decide which evidence to read next (the path through a
reconciliation failure is different from the path through a renamed column), call tools, and end with a
machine-checkable diagnosis. Options considered:

| Option | Why not (for this release) |
| --- | --- |
| Single prompt with all evidence | Bundles reach about 70 KB of JSON; dumping them in costs more, hides the investigation path, and removes the evidence ledger that grounding relies on |
| SDK tool runner | Good default, but the harness needs a tool budget, a forced final turn, refusal handling, and a span per turn and tool call; the runner's hooks could do most of it, the plain loop does all of it in about 100 lines |
| Managed Agents / Claude Agent SDK | Both bring a sandbox and general tools (bash, files) that this read-only design does not want |
| A multi-agent framework | No independent sub-tasks to parallelize inside one incident; more moving parts to secure and evaluate |

## Decision

`drc.agents.claude` runs a manual tool-use loop on the Messages API:

- **Model:** `claude-opus-5-5`, adaptive thinking (its default), explicit `effort` (default `high`;
  configurable, so cost against quality can be measured rather than assumed).
- **Tools:** the ten read-only tools with `strict: true` schemas.
- **Final answer:** `output_config.format` with a JSON schema whose `category` and `action_type` fields are
  enums over the taxonomy and the remediation catalog. The model cannot express an action outside the
  catalog; the policy check still validates every proposal against the evidence (defense in depth).
- **Budget:** at most 24 tool calls. When the budget is spent, the next turn sets `tool_choice: none` and
  asks for the final answer, so an investigation always ends with a diagnosis or an explicit abstention.
- **Caching:** top-level `cache_control` caches the static system prompt and tools and each turn's prefix;
  the system prompt contains no per-incident data so the prefix is identical across incidents.
- **Refusals:** server-side `fallbacks: "default"` retries a safety-classifier decline on the model
  Anthropic recommends for that category; a remaining refusal becomes an abstention, and which model
  served each turn is recorded.
- **Untrusted data:** the alert text is wrapped and labeled, and the system prompt states that tool output
  is data that may contain instructions to ignore.

## Consequences

- Cost and latency are recorded per incident (`drc.pricing`) and reported by the evaluation, so model and
  effort changes are decisions backed by numbers.
- Thinking blocks are passed back unchanged (the loop appends `response.content` as-is), which keeps the
  conversation append-only.
- Provider portability is limited to the Anthropic SDK's clients (Claude API, Bedrock, Vertex AI,
  Foundry). Server-side fallbacks are a Claude API feature; on other platforms `--no-fallbacks` uses the
  standard endpoint.
