# Guardrails Quick Reference

**Status**: ✅ **ENABLED** — All guardrails automatically enforced

---

## Four Guardrail Types

### 1️⃣ Input Guardrails (Safety)

**Blocks**:
- Questions shorter than 3 characters
- Questions longer than 3000 characters
- Questions with >500 words
- Questions containing: secret, password, api_key, token, confidential, private_key

**When Enforced**: Before processing
**How It Fails**: `ValueError: Input validation failed`

```python
from src.guardrails import InputGuardrails

valid, violations = InputGuardrails.validate(question)
# Returns: (bool, list[GuardrailViolation])
```

---

### 2️⃣ Output Guardrails (Quality)

**Checks**:
- Answer length (10–10,000 characters)
- Presence of sources
- Confidence score (≥0.5)

**When Enforced**: After generation
**How It Fails**: Warning logged, but answer returned

```python
from src.guardrails import OutputGuardrails

valid, violations = OutputGuardrails.validate(
    answer=generated_text,
    confidence=0.8,
    sources=retrieved_docs
)
```

---

### 3️⃣ Cost Guardrails (Budget)

**Limits**:
- 2,000 tokens per query
- 10,000 tokens per minute
- 100,000 tokens per hour
- 60 queries per minute

**When Enforced**: Before and after processing
**How It Fails**: `ValueError: Token limit exceeded`

```python
from src.guardrails import get_cost_tracker

tracker = get_cost_tracker()

# Check before processing
valid, v = tracker.check_tokens(in_tokens=150, out_tokens=350)

# Calculate cost
cost = tracker.calculate_cost(in_tokens=150, out_tokens=350)

# Get statistics
stats = tracker.get_usage_stats()
```

---

### 4️⃣ Quality Guardrails (RAGAS)

**Thresholds**:
- Min faithfulness: 0.7 (grounded in context)
- Min relevance: 0.6 (addresses question)
- Min context precision: 0.5 (relevant docs)

**When Enforced**: When quality metrics available
**How It Fails**: Warning logged, answer returned

```python
from src.guardrails import QualityGuardrails

valid, violations = QualityGuardrails.validate(
    faithfulness=0.85,
    relevance=0.78,
    context_precision=0.92
)
```

---

## Integration (Automatic)

### In CLI
```bash
python -m src.cli ask "What is RAG?" --mode crag
# ✅ Input guardrails enforced automatically
# ✅ Output guardrails checked automatically
# ✅ Cost tracked automatically
```

### In API
```bash
python -m uvicorn src.api.server:app --reload
# ✅ All guardrails enforced on every request
```

### In Streamlit
```bash
streamlit run streamlit_app.py
# ✅ All guardrails enforced on every interaction
```

---

## Cost Monitoring

### Track Usage

```python
from src.guardrails import get_cost_tracker

tracker = get_cost_tracker()

# After each query
cost = tracker.calculate_cost(input_tokens=150, output_tokens=350)
# Returns: 0.0255 (USD)

# Get stats
stats = tracker.get_usage_stats()
# {
#   "queries_per_minute": 12,
#   "tokens_per_minute": 4500,
#   "tokens_per_hour": 45000,
#   "total_queries": 450
# }
```

### Pricing (OpenAI GPT-4)

| Metric | Cost |
|--------|------|
| Per 1K input tokens | $0.03 |
| Per 1K output tokens | $0.06 |

**Example**: 150 input + 350 output = $0.0255

---

## Configuration

### Customize Limits

```python
from src.guardrails import InputGuardrails, CostGuardrails, QualityGuardrails

# Input
InputGuardrails.MAX_QUESTION_CHARS = 5000

# Cost
CostGuardrails.MAX_TOKENS_PER_MINUTE = 20000

# Quality
QualityGuardrails.MIN_FAITHFULNESS = 0.8
```

### Add Blocked Keywords

```python
from src.guardrails import InputGuardrails

InputGuardrails.BLOCKED_KEYWORDS.append("custom_keyword")
```

---

## Violation Handling

### Check Violations

```python
from src.guardrails import InputGuardrails

valid, violations = InputGuardrails.validate(question)

for v in violations:
    print(f"Rule: {v.rule}")
    print(f"Severity: {v.severity}")  # "error" or "warning"
    print(f"Message: {v.message}")
    print(f"Value: {v.value} (limit: {v.limit})")
```

### Violation Types

| Type | Severity | Action |
|------|----------|--------|
| Input length | error | Block query |
| Blocked keyword | error | Block query |
| Cost exceeded | error | Block query |
| Low quality | warning | Log, continue |
| No sources | warning | Log, continue |

---

## Monitoring

### Log Violations

```python
import logging

logger = logging.getLogger(__name__)

valid, violations = InputGuardrails.validate(question)
for v in violations:
    if v.severity == "error":
        logger.error(f"{v.rule}: {v.message}")
    else:
        logger.warning(f"{v.rule}: {v.message}")
```

### Set Alerts

```python
from src.guardrails import get_cost_tracker

tracker = get_cost_tracker()
stats = tracker.get_usage_stats()

if stats['tokens_per_hour'] > 80000:
    send_alert("⚠️  Approaching hourly token limit")

if stats['queries_per_minute'] > 50:
    send_alert("⚠️  High query rate")
```

---

## Default Limits

### Input Validation
- Min length: 3 characters
- Max length: 3000 characters
- Max words: 500
- Blocked: secret, password, api_key, token, confidential, private_key

### Output Validation
- Min length: 10 characters
- Max length: 10,000 characters
- Min confidence: 0.5

### Cost Limits
- Per query: 2,000 tokens
- Per minute: 10,000 tokens
- Per hour: 100,000 tokens
- Rate: 60 queries/minute

### Quality Thresholds
- Min faithfulness: 0.7
- Min relevance: 0.6
- Min context precision: 0.5

---

## Testing

### Test Input Validation

```python
from src.guardrails import InputGuardrails

# Valid
valid, v = InputGuardrails.validate("What is RAG?")
assert valid

# Too short
valid, v = InputGuardrails.validate("ab")
assert not valid

# Blocked keyword
valid, v = InputGuardrails.validate("What is my secret password?")
assert not valid
```

### Test Cost Tracking

```python
from src.guardrails import CostGuardrails

tracker = CostGuardrails()

# Check tokens
valid, v = tracker.check_tokens(in_tokens=150, out_tokens=350)
assert valid

# Calculate cost
cost = tracker.calculate_cost(in_tokens=150, out_tokens=350)
assert cost > 0
```

---

## Common Commands

```bash
# Check if guardrails are working
python -c "from src.guardrails import InputGuardrails; print('✅ Guardrails loaded')"

# Test input validation
python -c "
from src.guardrails import InputGuardrails
valid, v = InputGuardrails.validate('What is RAG?')
print(f'Valid: {valid}')
"

# Test cost tracking
python -c "
from src.guardrails import get_cost_tracker
tracker = get_cost_tracker()
cost = tracker.calculate_cost(150, 350)
print(f'Cost: \${cost:.4f}')
"

# See usage stats
python -c "
from src.guardrails import get_cost_tracker
stats = get_cost_tracker().get_usage_stats()
print(stats)
"
```

---

## Files

| File | Purpose |
|------|---------|
| `src/guardrails.py` | Core guardrails implementation |
| `docs/GUARDRAILS.md` | Comprehensive guide |
| `GUARDRAILS_QUICK_REFERENCE.md` | This file |
| `src/runner.py` | Integration point |

---

## Summary

✅ **Input Guardrails**: Validate user input before processing  
✅ **Output Guardrails**: Check answer quality and sources  
✅ **Cost Guardrails**: Track and limit token usage  
✅ **Quality Guardrails**: Enforce RAGAS quality standards  

**Automatically enforced in**:
- ✅ CLI
- ✅ API
- ✅ Streamlit

**Status**: ENABLED and WORKING ✅

---

**Protect your system. Keep it safe and cost-effective!** 🛡️💰
