"""Behavioral anomaly / drift detection — a second, independent cheat-signal.

This package ports AgentScope's per-run anomaly engine (``agentscope-anomaly``)
into Agent Exchange as a *per-agent* drift detector. Where AgentScope keyed its
baselines off an OTEL span database (one ``RunSummary`` per whole run), Agent
Exchange keys them off the marketplace's natural unit of work: one
:class:`~agent_exchange.anomaly.types.JobTelemetry` row per ``(agent, job)``.

The drift signal is deliberately *decoupled* from the verifier. The verifier
asks "is this deliverable's content real?" (claim-level, content-based). The
drift detector asks "is this agent behaving like itself?" (statistical,
behavior-based) — catching the cheat the verifier structurally can't see: an
agent that quietly swaps its declared frontier model for a cheap one while still
charging the frontier price. The two signals feed reputation independently, so a
worker has to beat *both* to get paid and keep its standing.

Layering (all downstream of :mod:`.types`, the fixed schema seam):

* :mod:`.types`       — dataclasses, enums, thresholds, drift-result types.
* :mod:`.telemetry`   — the per-agent JSON telemetry store (write/read/baseline).
* :mod:`.drift`       — the cost / latency / behavioral / model-substitution
                        detectors that read a baseline and a current row.
"""
