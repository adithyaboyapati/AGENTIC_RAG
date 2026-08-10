"""Load profile for the Agentic RAG API.

Timeouts, circuit breakers, rate limits, and the concurrency ceiling are all
configured — this is what actually exercises them together.

    locust -f tests/load/locustfile.py --host http://localhost:8000

Headless, for CI or a quick smoke:

    locust -f tests/load/locustfile.py --host http://localhost:8000 \
        --headless -u 20 -r 5 -t 2m

Set API_KEY in the environment when the target requires authentication.

What to watch:
  - 503 responses  → concurrency ceiling engaging (expected under saturation;
                     it should stay fast, not turn into 504s)
  - 429 responses  → rate limits engaging (expected; check Retry-After)
  - 504 responses  → requests exceeding REQUEST_TIMEOUT_SECONDS (investigate)
  - p95 latency    → compare against the histogram buckets in /metrics
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, events, task

API_KEY = os.getenv("API_KEY", "")

QUESTIONS = [
    "What is retrieval-augmented generation?",
    "What is Self-RAG?",
    "Compare naive RAG, advanced RAG, and modular RAG",
    "What fallback does CRAG use when retrieval fails?",
    "How does query decomposition improve multi-part questions?",
    "What is the role of a document grader in corrective RAG?",
]

# Weighted toward the cheap modes, as real traffic tends to be.
MODES = ["baseline"] * 5 + ["router"] * 3 + ["crag"] * 2 + ["agentic"]


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers


class RagUser(HttpUser):
    wait_time = between(1, 4)

    @task(6)
    def query(self) -> None:
        payload = {
            "question": random.choice(QUESTIONS),
            "mode": random.choice(MODES),
            "use_memory": False,
        }
        with self.client.post(
            "/query",
            json=payload,
            headers=_headers(),
            catch_response=True,
            name="POST /query",
        ) as response:
            # Backpressure is correct behaviour under load, not a failure.
            if response.status_code in (429, 503):
                response.success()
            elif response.status_code == 200 and not response.json().get("answer"):
                response.failure("200 with empty answer")

    @task(2)
    def query_stream(self) -> None:
        payload = {
            "question": random.choice(QUESTIONS),
            "mode": "baseline",
            "use_memory": False,
        }
        with self.client.post(
            "/query/stream",
            json=payload,
            headers=_headers(),
            stream=True,
            catch_response=True,
            name="POST /query/stream",
        ) as response:
            if response.status_code in (429, 503):
                response.success()
                return
            if response.status_code != 200:
                response.failure(f"status {response.status_code}")
                return
            saw_done = False
            for line in response.iter_lines():
                if line and b'"type": "done"' in line:
                    saw_done = True
            if not saw_done:
                response.failure("stream ended without a done event")

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="GET /health")


@events.test_stop.add_listener
def _report(environment, **_kwargs) -> None:
    stats = environment.stats.total
    print(
        f"\nrequests={stats.num_requests} failures={stats.num_failures} "
        f"p95={stats.get_response_time_percentile(0.95)}ms "
        f"p99={stats.get_response_time_percentile(0.99)}ms"
    )
