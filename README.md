<p align="center">
  <img src="assets/nxp_logo.png" alt="Nexus Exchange Protocol Logo" width="540"/>
</p>

<h1 align="center">Nexus Exchange Protocol (NXP)</h1>

<p align="center">
  <em>"The harmony of a swarm is not in the strength of its individual nodes, but in the swiftness of their exchange."</em>
</p>

<p align="center">
  <a href="https://github.com/Saran-nns/nxp"><img src="https://img.shields.io/badge/pypi-coming_soon-blue.svg" alt="PyPI Status"/></a>
  <a href="https://polyformproject.org/licenses/noncommercial/1.0.0"><img src="https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue.svg" alt="License"/></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python Version"/></a>
</p>

**Nexus Exchange Protocol (NXP)** is an architectural framework and zero-trust protocol built specifically for autonomous agent swarms. While traditional web stacks treat inter-agent communication like heavy, independent web services, NXP coordinates specialized agents like nodes in a high-performance distributed operating system.

Traditional agent frameworks rely on legacy REST or JSON-RPC protocols where every call must traverse text serialization pipelines and central authentication gateways. When chaining dozens of specialized agents together to solve complex workflows, this legacy overhead leads to administrative bottlenecks, fragile state management, and cascading swarm failures. NXP solves this holistically by uniting compact binary framing, embedded zero-trust cryptography, durable workflow checkpointing, and universal transport switching into a single protocol.

---

## Why NXP?

| Dimension | Traditional Agent Stacks (REST / JSON-RPC) | Nexus Exchange Protocol (NXP) |
| :--- | :--- | :--- |
| **Swarm Architecture** | **Centralized Web Services**: Treats internal agent calls like external web endpoints behind heavy API gateways. | **Distributed Neural Mesh**: Coordinates autonomous agent swarms like a unified, multi-core operating system. |
| **Security & Auth** | **Gateway Bottlenecks**: Relies on external auth server round-trips (OAuth/JWT) to validate every inter-agent call. | **Decentralized Zero-Trust**: Direct X25519 session-key negotiation & 4-byte SDMT token verification per frame without external dependencies. |
| **Protocol Efficiency** | **Verbose Text Serialization**: Heavy JSON parsing, string encoding, and bloated web headers on every call. | **Compact Binary Frame Protocol (BFP)**: High-density binary framing engineered specifically for lightweight agent-to-agent payloads. |
| **Swarm Resilience** | **Cascading Failures**: Errors in deep agent chains trigger domino timeouts and lost intermediate execution state. | **Durable Orchestration**: Built-in client circuit breakers, token-bucket sandboxing, and checkpointed `StateGraph` workflows. |
| **Transport Portability** | **Protocol Silos**: Forces developers to write custom wrapper adapters for HTTP, WebSockets, gRPC, or MCP. | **Universal Agent Definition**: A single agent definition automatically serves HTTP, WebSocket, gRPC, and stdio MCP. |

---

## Key Features

- **Binary Frame Protocol (BFP).** Fixed-overhead binary frames instead of verbose JSON-RPC, served over HTTP, WebSocket, gRPC, or stdio MCP from the same agent definition.
- **Authenticated by default.** An HMAC connection handshake plus a real X25519 session-key exchange, then a 4-byte SDMT token authenticating every subsequent frame — see [Two Identity Systems](#two-identity-systems) for exactly what secures what.
- **Durable, resilient orchestration.** Checkpointed `StateGraph` workflows, a real client-side circuit breaker, and a token-bucket sandbox for per-caller rate limiting.
- **Agent discovery with dedup.** Agent Card manifests with a Blake2b hash-and-`CARD_HIT` handshake to skip retransmitting an unchanged card.

---

## Installation

Currently, NXP (`nexes`) is installed locally from the repository source:

### 1. Install from GitHub

```bash
pip install git+https://github.com/Saran-nns/nxp.git
```

### 2. Local Editable Installation

```bash
git clone https://github.com/Saran-nns/nxp.git
cd nxp
pip install -e .
```

Optional transports and features are extras:

```bash
pip install -e ".[grpc]"   # gRPC transport
pip install -e ".[all]"    # everything
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
