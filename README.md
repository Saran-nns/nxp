# Nexus Exchange Protocol (NXP) Python SDK

[![PyPI Version](https://img.shields.io/pypi/v/nxp.svg)](https://pypi.org/project/nxp/)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue.svg)](https://polyformproject.org/licenses/noncommercial/1.0.0)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)

**Nexus Exchange Protocol (NXP)** is an Agent-to-Agent (A2A) framework for building, serving, and orchestrating multi-agent systems: a compact binary wire protocol (BFP), HTTP/WebSocket/gRPC transports, an authenticated connection handshake, durable workflow orchestration, and a per-caller rate-limiting sandbox.

Every number in this README is a real, reproducible measurement — see [Benchmarks](#benchmarks) for how each one was produced.

---

## Key Features

- **Compact binary wire framing (BFP).** Fixed-overhead binary frames (1-byte opcode + 3-byte sequence, then a type-specific body) instead of verbose JSON-RPC, with a MessagePack-encoded payload.
- **Authenticated connection handshake.** `NXPClient`/`NXPTransport` connections are authenticated via an HMAC-SHA256 `did:nxp:<name>:<fingerprint>` handshake, followed by a real X25519 ECDH key exchange to derive a per-connection session key. A separate, standalone `Ed25519Identity` (`did:key:z6M...`) module is available for self-sovereign asymmetric signing where a shared secret isn't an option — see [Two Identity Systems](#two-identity-systems) below for which one secures what.
- **Per-frame authentication.** Once connected, every `CALL`/`TOOL` frame carries a 4-byte Sequence-Derived Micro-Token (SDMT) derived from the session key, checked against a sliding-window replay defense.
- **Tool sandboxing & rate limiting.** A real token-bucket `ToolSandbox`, keyed per caller identity, bounds per-caller throughput.
- **Durable `StateGraph` workflows.** Checkpointed DAG-based workflow execution for multi-step agent pipelines.
- **Client-side circuit breaker.** A real `CircuitBreaker` FSM (`CLOSED` → `OPEN` → `HALF_OPEN`) wired into `NXPClient.call()`: once a node's error rate crosses a threshold, further calls fail fast — rejected locally, no network attempt — until a cooldown elapses and trial probes confirm recovery. This protects one client from hammering one struggling node; it does not (yet) reroute work to a healthy replica.
- **Multi-transport serving.** Serve the same agent definition over HTTP (A2A), WebSocket (BFP), gRPC, and a self-contained stdio MCP transport (a hand-rolled JSON-RPC 2.0 implementation — it does not depend on the third-party `fastmcp` package).
- **Agent Card discovery with dedup.** Agents publish a JSON Agent Card manifest; a Blake2b hash-and-`CARD_HIT` handshake skips retransmitting it when a peer's cached copy is still current.

---

## Installation

```bash
pip install nxp
```

Optional transports and features are extras:

```bash
pip install "nxp[grpc]"   # gRPC transport
pip install "nxp[all]"    # everything
```

Base install only requires `fastapi`, `uvicorn`, `httpx`, `pydantic`, `anyio`, `typer`, `rich`, `websockets`, `msgpack`, and `cryptography` — `import nxp` does not require any of the extras. HMAC bearer API-key auth (`nxp.security.auth`) works out of the box; it does not need the `auth` extra, which currently declares dependencies the implementation doesn't use.

---

## Quickstart

```python
from nxp import NXPAgent, connect

agent = NXPAgent(
    name="calculator-agent",
    description="High-performance math agent",
    version="1.0.0",
)

@agent.skill(tags=["math"])
async def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b

if __name__ == "__main__":
    agent.run(port=8000)
```

From another process:

```python
import asyncio
from nxp import connect

async def call_agent():
    client = connect("http://localhost:8000")
    card = await client.get_card()
    print(f"Connected to: {card.name}")

    result = await client.call("add", a=42.0, b=58.0)
    print(f"Result: {result}")  # 100.0

asyncio.run(call_agent())
```

---

## Two Identity Systems

NXP ships two distinct identity mechanisms for two distinct jobs — they are not interchangeable, and only one of them secures the live connection handshake:

| | `Identity` (`nxp.identity`) | `Ed25519Identity` (`nxp.security.crypto`) |
|---|---|---|
| DID format | `did:nxp:<name>:<fingerprint>` | `did:key:z6M...` |
| Mechanism | Shared-secret HMAC-SHA256 | Asymmetric Ed25519 keypair, no shared secret |
| Used by | `NXPTransport`/`NXPClient`'s real connection handshake | Standalone payload signing/verification |
| Wired into the WebSocket handshake? | **Yes** — this is what actually authenticates a connection today | No — real and independently useful, but not (yet) part of the connection path |

Per-frame authentication after the handshake uses a separate 4-byte SDMT HMAC token derived from an X25519-negotiated session key, not either DID system directly.

---

## Benchmarks

All figures below are real measurements taken against this codebase, not estimates. The benchmark scripts themselves live in this SDK's development repository rather than here; figures are cited by experiment number for traceability.

| Metric | Result | Source |
|---|---|---|
| In-process skill dispatch | `0.06 µs` / 18.01M req/s — 1876× faster than LangChain `StructuredTool` (`104.10 µs`) | Experiment 01 |
| BFP wire frame (skill call + reply) | `~98 µs`, 55% smaller on the wire than raw JSON | Experiment 01b |
| Agent Card discovery (`CARD_HIT`, cache hit) | `90.60 µs`, 79% smaller than a full JSON card fetch | Experiment 01b |
| Circuit breaker fail-fast rejection | `2.2 µs` (vs. a full network round-trip) while `OPEN` | Experiment 08 |
| SDMT per-frame verification | `~2.86 µs` | Chapter 4 crypto benchmark |
| X25519 session-key derivation (once per connection) | `~613 µs` | Chapter 4 crypto benchmark |
| Real 3-agent delegation pipeline (2 MB payload) | `55.76 ms` vs. `230.65 ms` over WebSocket+JWT — 4.14× faster, 50% less wire data | Real end-to-end swarm benchmark |

---

## License

**[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)** — free for any noncommercial purpose (personal use, research, education, nonprofits). **Commercial use is not permitted** under this license. If you want to use NXP commercially, contact the author to discuss a separate license.

Copyright © Saranraj Nambusubramaniyan.
