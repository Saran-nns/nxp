# Nexus Exchange Protocol (NXP) Python SDK

[![PyPI Version](https://img.shields.io/pypi/v/nxp.svg)](https://pypi.org/project/nxp/)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue.svg)](https://polyformproject.org/licenses/noncommercial/1.0.0)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)

**Nexus Exchange Protocol (NXP)** is a low-overhead, zero-trust protocol and framework for autonomous agent swarms — the layer that lets specialized agents talk to each other and execute reliably without legacy web-protocol overhead getting in the way.

It exists because that overhead is real: modern specialized AI tools execute in microseconds, but framing a call as JSON text and authenticating it through a central security gateway can cost 10–50× the actual compute time per call — for a swarm chaining 50 internal calls to solve one task, that's over 100ms of pure administrative waiting before any real work happens. NXP replaces that stack with a compact Binary Frame Protocol (BFP), a per-frame zero-trust handshake that needs no external auth-server round-trip, and — above the wire layer — the durable orchestration and resilience primitives a single agent or a whole swarm needs to actually run in production.

---

## Key Features

- **Binary Frame Protocol (BFP).** Fixed-overhead binary frames instead of verbose JSON-RPC, served over HTTP, WebSocket, gRPC, or stdio MCP from the same agent definition.
- **Authenticated by default.** An HMAC connection handshake plus a real X25519 session-key exchange, then a 4-byte SDMT token authenticating every subsequent frame — see [Two Identity Systems](#two-identity-systems) for exactly what secures what.
- **Durable, resilient orchestration.** Checkpointed `StateGraph` workflows, a real client-side circuit breaker, and a token-bucket sandbox for per-caller rate limiting.
- **Agent discovery with dedup.** Agent Card manifests with a Blake2b hash-and-`CARD_HIT` handshake to skip retransmitting an unchanged card.

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
from nxp import NXPAgent

agent = NXPAgent(
    name="utils-agent",
    description="Small utility agent with a couple of independent skills",
    version="1.0.0",
)

@agent.skill(tags=["math"])
async def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b

@agent.skill(tags=["text"])
async def word_count(text: str) -> int:
    """Count words in a string."""
    return len(text.split())

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
    print(f"Connected to: {card.name}, skills: {[s.id for s in card.skills]}")

    result = await client.call("add", a=42.0, b=58.0)
    print(f"add(42, 58) = {result}")

    count = await client.call("word_count", text="the quick brown fox")
    print(f"word_count(...) = {count}")

asyncio.run(call_agent())
```

---

## Two Identity Systems

NXP ships two distinct identity mechanisms for two distinct jobs — they are not interchangeable, and only one of them secures the live connection handshake:

| | `Identity` (`nxp.security.identity`) | `Ed25519Identity` (`nxp.security.crypto`) |
|---|---|---|
| DID format | `did:nxp:<name>:<fingerprint>` | `did:key:z6M...` |
| Mechanism | Shared-secret HMAC-SHA256 | Asymmetric Ed25519 keypair, no shared secret |
| Used by | `NXPTransport`/`NXPClient`'s real connection handshake | Standalone payload signing/verification |
| Wired into the WebSocket handshake? | **Yes** — this is what actually authenticates a connection today | No — real and independently useful, but not (yet) part of the connection path |

Per-frame authentication after the handshake uses a separate 4-byte SDMT HMAC token derived from an X25519-negotiated session key, not either DID system directly.

---

## License

**[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)** — free for any noncommercial purpose (personal use, research, education, nonprofits). **Commercial use is not permitted** under this license. If you want to use NXP commercially, contact the author to discuss a separate license.

Copyright © Saranraj Nambusubramaniyan.
