# Legacy Retirement Inventory (Phase 7)

| Legacy Component | Referenced By | Runtime-Critical? | Removed? | Evidence |
| ---------------- | ------------- | ----------------- | -------- | -------- |
| `router_graph.py` | runner (removed) | No | Yes | Replaced by canonical classify/retrieve |
| `crag_graph.py` | runner (removed) | No | Yes | Replaced by canonical evidence + rewrite |
| `decompose_graph.py` | agent_graph (removed) | No | Yes | Replaced by canonical decompose strategy |
| `multi_hop_graph.py` | agent_graph (removed) | No | Yes | Replaced by canonical multi_hop strategy |
| `tools_graph.py` | agent_graph (removed) | No | Yes | Replaced by canonical federation retrieval |
| `agent_graph.py` | runner default (removed) | No | Yes | Replaced by `canonical_graph.py` |
| `consensus_graph.py` | API mode consensus | No | Yes | Deprecated; maps to canonical auto |
| `rag/baseline.py` | runner (removed) | No | Yes | Replaced by canonical simple path |
| Legacy `_dispatch` branches | runner | No | Yes | Single canonical dispatch |
| `to_legacy_adapter` | canary path | No | Deprecated | `contracts.api_response.canonical_to_api_response` |
| API legacy mode enum values | server, frontend | No | Deprecated | Mapped to canonical; telemetry emitted |
| `shared_nodes.py` | canonical_graph | **Yes** | **No** | Shared router/direct/web helpers |
| `chains/generation.py` | canonical + shared_nodes | **Yes** | **No** | `rag_chain`, direct/web chains |
| `shadow_eval.db` rows | gates, retirement | No | **No** | Historical paired metrics preserved |
| Traffic policy / canary | server | **Yes** | **No** | Rollback safety retained |

Inspect live status: `GET /ops/legacy/retirement`
