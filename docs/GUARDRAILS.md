# Production Guardrails — Safety, Quality, and Cost Control

**Purpose**: Protect your production system with automatic safety checks, cost limits, and quality standards.

---

## Overview

Guardrails are **automatic safety gates** that prevent:

✅ **Invalid Input** — Malicious or malformed questions  
✅ **Cost Overruns** — Excessive token usage and expenses  
✅ **Quality Failures** — Low-quality or unsafe answers  
✅ **Resource Exhaustion** — Rate limiting and DOS prevention  

---

## Four Guardrail Categories

### 1. Input Guardrails

**What They Check**:
- Question length (3–3000 characters)
- Word count (max 500 words)
- Blocked keywords (secrets, passwords, keys)
- Character validation

**Configuration** (`src/guardrails.py`):
```python
class InputGuardrails:
    MAX_QUESTION_LENGTH = 500      # words
    MAX_QUESTION_CHARS = 3000      # characters
    MIN_QUESTION_CHARS = 3         # characters
    BLOCKED_KEYWORDS = [
        "secret", "password", "api_key", "token",
        "confidential", "private_key"
    ]
```

**Usage**:
```python
from src.guardrails import InputGuardrails

valid, violations = InputGuardrails.validate(user_question)
if not valid:
    for v in violations:
        print(f"❌ {v.rule}: {v.message}")
```

**Example Violations**:
```
❌ min_length: Question too short (minimum 3 characters)
❌ max_length: Question too long (maximum 3000 characters)
❌ max_words: Question too many words (maximum 500)
❌ blocked_keyword: Question contains blocked keyword: 'secret'
```

---

### 2. Output Guardrails

**What They Check**:
- Answer length (10–10,000 characters)
- Presence of sources
- Confidence scores
- Content validation

**Configuration** (`src/guardrails.py`):
```python
class OutputGuardrails:
    MIN_ANSWER_CHARS = 10          # minimum answer length
    MAX_ANSWER_CHARS = 10000       # maximum answer length
    MIN_CONFIDENCE = 0.5           # 0.0-1.0 score
```

**Usage**:
```python
from src.guardrails import OutputGuardrails

valid, violations = OutputGuardrails.validate(
    answer=generated_answer,
    confidence=0.8,
    sources=retrieved_docs
)
```

**Example Violations**:
```
⚠️  min_answer_length: Answer too short (minimum 10 characters)
⚠️  max_answer_length: Answer too long (maximum 10000 characters)
⚠️  low_confidence: Confidence score too low (minimum 0.5)
⚠️  no_sources: Answer has no retrieved sources
```

---

### 3. Cost Guardrails

**What They Track**:
- Tokens per query
- Tokens per minute
- Tokens per hour
- Cost in USD

**Configuration** (`src/guardrails.py`):
```python
class CostGuardrails:
    MAX_TOKENS_PER_QUERY = 2000       # per single query
    MAX_TOKENS_PER_MINUTE = 10000     # per 60 seconds
    MAX_TOKENS_PER_HOUR = 100000      # per 3600 seconds
    MAX_QUERIES_PER_MINUTE = 60       # rate limit
    
    # OpenAI pricing (GPT-4)
    COST_PER_1K_INPUT = 0.03
    COST_PER_1K_OUTPUT = 0.06
```

**Usage**:
```python
from src.guardrails import get_cost_tracker

tracker = get_cost_tracker()

# Check before processing
valid, violations = tracker.check_tokens(
    input_tokens=150,
    output_tokens=300
)

# Calculate cost
cost = tracker.calculate_cost(input_tokens=150, output_tokens=300)
print(f"Cost: ${cost:.4f}")

# Get stats
stats = tracker.get_usage_stats()
# {
#   "queries_per_minute": 12,
#   "tokens_per_minute": 4500,
#   "tokens_per_hour": 45000,
#   "total_queries": 450
# }
```

**Example Violations**:
```
❌ tokens_per_query: Query exceeds token limit (2500 > 2000)
❌ tokens_per_minute: Minute token limit exceeded (12000 > 10000)
❌ tokens_per_hour: Hour token limit exceeded (105000 > 100000)
```

---

### 4. Quality Guardrails

**What They Check**:
- Answer faithfulness (grounded in context, no hallucinations)
- Answer relevance (addresses the question)
- Context precision (retrieved docs are relevant)

**Configuration** (`src/guardrails.py`):
```python
class QualityGuardrails:
    MIN_RELEVANCE = 0.6            # answer relevance score
    MIN_CONTEXT_PRECISION = 0.5    # fraction of relevant docs
    MIN_FAITHFULNESS = 0.7         # grounding in context
```

**Usage**:
```python
from src.guardrails import QualityGuardrails

valid, violations = QualityGuardrails.validate(
    faithfulness=0.85,       # RAGAS metric
    relevance=0.78,          # RAGAS metric
    context_precision=0.92   # RAGAS metric
)
```

**Example Violations**:
```
⚠️  low_faithfulness: Answer not grounded in context (0.65 < 0.7)
⚠️  low_relevance: Answer not sufficiently relevant (0.55 < 0.6)
⚠️  low_context_precision: Retrieved docs not precise (0.4 < 0.5)
```

---

## Integration Points

### In CLI
```python
# src/cli.py automatically enforces guardrails
from src.runner import run_agent

try:
    result = run_agent(user_question, mode="crag")
    # Input guardrails checked automatically
    # Output guardrails checked automatically
except ValueError as e:
    print(f"❌ Guardrail violated: {e}")
```

### In API
```python
# src/api/server.py integrates guardrails
from fastapi import HTTPException

@app.post("/query")
async def query_endpoint(request: QueryRequest):
    try:
        result = run_agent(request.question, request.mode)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

### In Streamlit
```python
# streamlit_app.py integrates guardrails
from src.runner import run_agent

try:
    result = run_agent(user_input, selected_mode)
    st.success("✅ Query processed successfully")
except ValueError as e:
    st.error(f"❌ {e}")
```

---

## Cost Monitoring

### Track Token Usage

```python
from src.guardrails import get_cost_tracker

tracker = get_cost_tracker()

# After each query
cost = tracker.calculate_cost(input_tokens=150, output_tokens=350)
print(f"This query cost: ${cost:.4f}")

# Get aggregate stats
stats = tracker.get_usage_stats()
print(f"Queries this minute: {stats['queries_per_minute']}")
print(f"Tokens this hour: {stats['tokens_per_hour']}")
```

### Cost Calculation

For **OpenAI GPT-4**:
- Input tokens: $0.03 per 1K tokens
- Output tokens: $0.06 per 1K tokens

**Example**:
```
Input tokens: 150
Output tokens: 350
Total tokens: 500

Input cost: (150 / 1000) × $0.03 = $0.0045
Output cost: (350 / 1000) × $0.06 = $0.021
Total cost: $0.0255
```

---

## Quality Standards

### RAGAS Metrics Integration

Guardrails use RAGAS evaluation metrics:

```python
from src.guardrails import QualityGuardrails
from src.evaluation.metrics import evaluate_metrics

# Evaluate response quality
metrics = evaluate_metrics(question, answer, context)

# Check against quality guardrails
valid, violations = QualityGuardrails.validate(
    faithfulness=metrics.faithfulness,
    relevance=metrics.answer_relevance,
    context_precision=metrics.context_precision
)

if not valid:
    for v in violations:
        print(f"⚠️  Quality: {v.message}")
```

### Severity Levels

- **Error** — Block the response, reject the query
- **Warning** — Allow the response, but log the issue

---

## Configuration Management

### Override Defaults

```python
from src.guardrails import InputGuardrails, CostGuardrails

# Customize input limits
InputGuardrails.MAX_QUESTION_CHARS = 5000
InputGuardrails.MAX_QUESTION_LENGTH = 1000

# Customize cost limits
CostGuardrails.MAX_TOKENS_PER_QUERY = 3000
CostGuardrails.MAX_TOKENS_PER_MINUTE = 20000
```

### Environment-Based Configuration

```python
# For production (more strict)
if ENV == "production":
    CostGuardrails.MAX_TOKENS_PER_MINUTE = 5000
    QualityGuardrails.MIN_FAITHFULNESS = 0.8
    
# For development (more relaxed)
elif ENV == "development":
    CostGuardrails.MAX_TOKENS_PER_MINUTE = 100000
    QualityGuardrails.MIN_FAITHFULNESS = 0.5
```

---

## Monitoring & Alerts

### Log Violations

```python
import logging

logger = logging.getLogger(__name__)

valid, violations = InputGuardrails.validate(question)
for v in violations:
    if v.severity == "error":
        logger.error(f"Guardrail violation: {v.rule} - {v.message}")
    else:
        logger.warning(f"Guardrail warning: {v.rule} - {v.message}")
```

### Set Up Alerts

```python
from src.guardrails import get_cost_tracker

tracker = get_cost_tracker()
stats = tracker.get_usage_stats()

# Alert if approaching limits
if stats['tokens_per_hour'] > 80000:  # 80% of limit
    send_alert("⚠️  Approaching hourly token limit")

if stats['queries_per_minute'] > 50:  # 83% of limit
    send_alert("⚠️  High query rate")
```

---

## Best Practices

### 1. Validate Early
```python
# ✅ Good: Check input before processing
valid, violations = InputGuardrails.validate(question)
if not valid:
    raise ValueError("Invalid input")
result = run_agent(question, mode)

# ❌ Bad: Process first, validate later
result = run_agent(question, mode)
InputGuardrails.validate(question)  # Too late!
```

### 2. Track Costs Continuously
```python
# ✅ Good: Monitor costs throughout execution
tracker = get_cost_tracker()
for query in batch_queries:
    cost = tracker.calculate_cost(tokens_in, tokens_out)
    total_cost += cost

# ❌ Bad: Only check at the end
# Already spent money on invalid queries
```

### 3. Set Reasonable Limits
```python
# ✅ Good: Conservative limits with buffer
MAX_TOKENS_PER_HOUR = 80000  # 80% of budget
ALERT_THRESHOLD = 0.8

# ❌ Bad: Set limit at max budget
MAX_TOKENS_PER_HOUR = 100000  # Will hit limit exactly
```

### 4. Log Everything
```python
# ✅ Good: Detailed logging
logger.info(f"Query: {question[:50]}...")
logger.info(f"Mode: {mode}")
logger.info(f"Tokens: {in_tokens} input, {out_tokens} output")
logger.info(f"Cost: ${cost:.4f}")

# ❌ Bad: Sparse logging
# Can't debug issues later
```

---

## Testing Guardrails

### Unit Tests

```python
from src.guardrails import InputGuardrails, OutputGuardrails

def test_input_guardrails():
    # Too short
    valid, violations = InputGuardrails.validate("ab")
    assert not valid
    assert any(v.rule == "min_length" for v in violations)
    
    # Too long
    valid, violations = InputGuardrails.validate("a" * 4000)
    assert not valid
    assert any(v.rule == "max_length" for v in violations)
    
    # Valid
    valid, violations = InputGuardrails.validate("What is RAG?")
    assert valid
    assert len(violations) == 0
```

### Integration Tests

```python
from src.runner import run_agent

def test_guardrails_in_runner():
    # Should raise ValueError on invalid input
    with pytest.raises(ValueError):
        run_agent("secret", mode="crag")
    
    # Should succeed on valid input
    result = run_agent("What is RAG?", mode="crag")
    assert result.answer
```

---

## Production Deployment Checklist

- [ ] Enable all guardrails in production
- [ ] Set realistic cost limits based on budget
- [ ] Configure quality thresholds
- [ ] Set up monitoring and alerts
- [ ] Log all guardrail violations
- [ ] Review violations daily
- [ ] Test guardrails work correctly
- [ ] Document custom limits
- [ ] Train team on guardrails
- [ ] Set up cost tracking dashboard

---

## Common Issues

### Issue: Legitimate queries rejected
**Solution**: Adjust limits carefully, add to whitelist if needed
```python
InputGuardrails.BLOCKED_KEYWORDS.remove("sensitive_keyword")
```

### Issue: Spending too much on tokens
**Solution**: Lower token limits or optimize prompts
```python
CostGuardrails.MAX_TOKENS_PER_QUERY = 1000  # More strict
```

### Issue: Quality scores too low
**Solution**: Review retrieved documents, adjust thresholds if appropriate
```python
QualityGuardrails.MIN_FAITHFULNESS = 0.6  # More lenient
```

---

## Summary

Guardrails provide **defense-in-depth** for production RAG systems:

| Guardrail | Protects Against | Example |
|-----------|-----------------|---------|
| **Input** | Malicious input | Secret disclosure |
| **Output** | Bad answers | Too short, no sources |
| **Cost** | Budget overruns | Token limit exceeded |
| **Quality** | Low-quality answers | Hallucinations |

**All guardrails are automatically enforced in**:
- CLI (`python -m src.cli ask ...`)
- API (`POST /query`)
- Streamlit (`streamlit run streamlit_app.py`)

---

**Keep your system safe, fast, and cost-effective!** 🛡️💰📊
