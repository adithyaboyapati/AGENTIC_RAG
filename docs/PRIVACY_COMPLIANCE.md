# Privacy & Compliance — PII/PHI Data Protection

**Purpose**: Protect sensitive personal and health information in your system.

**Compliance Standards**: GDPR, HIPAA, CCPA

---

## Overview

Privacy protection includes:

✅ **PII Detection** — Social Security, credit cards, emails, phones, addresses  
✅ **PHI Detection** — Medical conditions, medications, insurance IDs  
✅ **Data Redaction** — Remove sensitive data from input/output  
✅ **Audit Logging** — Track sensitive data for compliance  
✅ **Policy Enforcement** — Block or redact based on configuration  

---

## PII (Personally Identifiable Information)

### What Gets Detected

| Type | Pattern | Example |
|------|---------|---------|
| **SSN** | XXX-XX-XXXX (dashes required) | 123-45-6789 |
| **Credit Card** | 4 groups of 4 digits | 1234-5678-9012-3456 |
| **Email** | user@domain.com | john@example.com |
| **Phone** | (123) 456-7890 or similar | (555) 123-4567 |
| **Address** | Street address with city/state | 123 Main St, Springfield |
| **Passport** | 1-2 letters + 6-9 digits | AB123456 |
| **Driver License** | 2 letters + 7-8 digits | CA1234567 |

> **Note:** the SSN pattern deliberately requires dashes (`\d{3}-\d{2}-\d{4}`). An earlier
> version also matched any bare 9-digit number, which false-positived on things like row
> counts or IDs ("the dataset has 123456789 rows"). Bare digit strings are no longer
> treated as SSNs.

### Detection Example

```python
from src.privacy import PIIDetector

text = "Contact John at john@example.com or 555-123-4567"
findings = PIIDetector.detect_all(text)

for finding in findings:
    print(f"Found {finding.data_type}: {finding.value}")
    # Output:
    # Found email: john@example.com
    # Found phone: 555-123-4567
```

---

## PHI (Protected Health Information)

### What Gets Detected

| Type | Examples |
|------|----------|
| **Medical Conditions** | diabetes, cancer, covid, hiv, depression, arthritis |
| **Medical Procedures** | surgery, chemotherapy, dialysis, vaccination |
| **Medications** | aspirin, metformin, lisinopril, sertraline |
| **Insurance ID** | 2 letters + 8-10 digits (XX12345678) |

### Detection Example

```python
from src.privacy import PHIDetector

text = "Patient diagnosed with diabetes, prescribed metformin"
findings = PHIDetector.detect_all(text)

for finding in findings:
    print(f"Found {finding.data_type}: {finding.value}")
    # Output:
    # Found medical: diabetes
    # Found medical: metformin
```

---

## Data Redaction

### Redact All Sensitive Data

```python
from src.privacy import DataRedactor

text = "John Smith called 555-123-4567 about his diabetes treatment"

# Redact PII only
pii_redacted = DataRedactor.redact_pii(text)
# Output: "[NAME] Smith called [PHONE] about his diabetes treatment"

# Redact PHI only
phi_redacted = DataRedactor.redact_phi(text)
# Output: "John Smith called 555-123-4567 about his [MEDICAL] treatment"

# Redact both
fully_redacted = DataRedactor.redact_all(text)
# Output: "[NAME] Smith called [PHONE] about his [MEDICAL] treatment"
```

### Mask Values

```python
from src.privacy import DataRedactor

# Mask credit card (reveal last 4 digits)
card = "1234567890123456"
masked = DataRedactor.mask_value(card, reveal_chars=4)
# Output: "************3456"

# Mask SSN
ssn = "123456789"
masked = DataRedactor.mask_value(ssn, reveal_chars=4)
# Output: "*****6789"
```

---

## Privacy Policy Configuration

### Default Policy

`PrivacyPolicy` is a dataclass — construct it with the behaviour you want rather than
mutating flags after the fact:

```python
from src.privacy import PrivacyMode, PrivacyPolicy

policy = PrivacyPolicy(
    input_mode=PrivacyMode.REDACT,   # off | redact | block  (default: redact)
    output_mode=PrivacyMode.REDACT,  # off | redact | block  (default: redact)
    detect_phi=False,                # PHI is opt-in (default: False)
    log_findings=True,               # log detections for audit
    data_retention_days=30,
    compliance_gdpr=False,
    compliance_hipaa=False,
    compliance_ccpa=False,
)
```

The legacy uppercase names (`BLOCK_ON_PII`, `REDACT_PHI`, …) still resolve as read-only
properties derived from the modes above, so older call sites keep working — but they
cannot be assigned. Set the modes instead.

### Why detection is context-aware

A privacy filter that fires too often is not "safer" — it silently corrupts correct
answers, which is a worse failure than missing a redaction on a corpus that contains no
PII. Two rules keep the false-positive rate down:

**Shape alone is not identity.** `AB12345678` is a chunk ID far more often than a
driver's licence, so identifier patterns (passport, licence, insurance/member ID) only
fire when introduced by a *label* — `Passport No: AB1234567`. Credit-card candidates
must additionally pass a **Luhn checksum**, so order numbers and hashes are ignored.

**A topic mention is not a disclosure.** `PHIDetector` requires clinical or possessive
context within a short window (`patient`, `diagnosed with`, `prescribed`, `my`, …)
before a medical term counts. So:

| Text | PHI? |
|---|---|
| `You can bypass the cache by setting CACHE_ENABLED=false` | No |
| `The COVID dataset is indexed in Chroma` | No |
| `What treatments exist for diabetes?` | No — informational, the intended use case |
| `Patient was diagnosed with diabetes and prescribed metformin` | Yes |

Ordinary English words that double as procedures (`bypass`, `recovery`, `screening`) are
excluded from the keyword list entirely.

### Why PHI is opt-in

PII and PHI are different risk classes and have separate switches. PHI detection is off
by default (`PRIVACY_DETECT_PHI=false`) because for a general-purpose corpus it produces
more noise than signal. Enable it for clinical deployments; combine with
`PRIVACY_INPUT_MODE=block` if your intake flow must reject any PHI outright.

### Custom Policies

```python
from src.privacy import PrivacyMode, PrivacyPolicy

# Healthcare (HIPAA) — detect PHI, reject it on the way in, short retention
healthcare = PrivacyPolicy(
    input_mode=PrivacyMode.BLOCK,
    output_mode=PrivacyMode.REDACT,
    detect_phi=True,
    compliance_hipaa=True,
    data_retention_days=7,
)

# European users (GDPR) — mask rather than reject, so the assistant stays usable
gdpr = PrivacyPolicy(
    input_mode=PrivacyMode.REDACT,
    output_mode=PrivacyMode.REDACT,
    compliance_gdpr=True,
    data_retention_days=30,
)

# Internal corpus with no personal data at all — skip the work entirely
internal = PrivacyPolicy(input_mode=PrivacyMode.OFF, output_mode=PrivacyMode.OFF)
```

---

## Runtime Configuration (Environment Variables)

`src.privacy.get_privacy_policy()` builds the policy used by `src.runner.run_agent()`
from `.env`. Behaviour is one explicit knob per direction:

```bash
# off | redact | block
PRIVACY_INPUT_MODE=redact     # default
PRIVACY_OUTPUT_MODE=redact    # default
PRIVACY_DETECT_PHI=false      # PHI is opt-in
PRIVACY_RETENTION_DAYS=30
```

| Mode | Input (`src.runner._prepare_agent_run`) | Output (`_apply_post_guardrails`) |
|---|---|---|
| `off` | Passed through untouched; nothing detected | Passed through untouched |
| `redact` | Sensitive spans masked, request proceeds | Answer masked (`john@example.com` → `[EMAIL]`) and returned |
| `block` | `ValueError` — the LLM never runs | `ValueError` — nothing is returned to the caller |

`redact` is the default in both directions. Rejecting a whole question because it
contains an email address is a poor experience for a document-QA product, and masking
gives the same protection.

Redaction happens **before** the cache key is computed, so the cache is keyed on the
sanitized question and redaction never splits the cache.

### Deprecated settings

`REDACT_OUTPUT_PII` and `BLOCK_OUTPUT_PII` still work — they are mapped onto
`PRIVACY_OUTPUT_MODE` at startup and logged as deprecation warnings. Note that the old
`REDACT_OUTPUT_PII` drove PII *and* PHI together; PHI now requires
`PRIVACY_DETECT_PHI=true`.

| Old | New |
|---|---|
| `REDACT_OUTPUT_PII=true` | `PRIVACY_OUTPUT_MODE=redact` |
| `REDACT_OUTPUT_PII=false` | `PRIVACY_OUTPUT_MODE=off` |
| `BLOCK_OUTPUT_PII=true` | `PRIVACY_OUTPUT_MODE=block` |
| `policy.BLOCK_ON_PII = True` | `PRIVACY_INPUT_MODE=block` |

---

## Data Retention

`PRIVACY_RETENTION_DAYS` documents intent; [`docs/supabase_schema.sql`](supabase_schema.sql)
enforces it. Applying that schema enables Row Level Security on `chat_messages` (deny by
default — only the service role the API uses can read it) and installs
`purge_expired_chat_messages(retention_days)` plus `delete_chat_session(session_id)` for
GDPR/CCPA erasure requests. Schedule the purge with `pg_cron` or your own scheduler.

---

## Privacy Guard

### Check Input for Sensitive Data

```python
from src.privacy import PrivacyGuard, DEFAULT_PRIVACY_POLICY

question = "My SSN is 123-45-6789"

# Check according to policy — ok=False only when a BLOCK_ON_* policy actually triggers.
# `findings` is always populated with anything detected, even when ok=True, so you can
# still log/redact non-blocking findings (e.g. PHI) downstream.
ok, findings = PrivacyGuard.check_input(question, DEFAULT_PRIVACY_POLICY)

if not ok:
    print("❌ Input blocked — contains sensitive data:")
    for f in findings:
        print(f"  - {f.data_type}: {f.value}")
else:
    print("✅ Input allowed")

# PHI mentions don't block by default — this passes even though "diabetes" is detected:
ok, findings = PrivacyGuard.check_input("What treatments exist for diabetes?", DEFAULT_PRIVACY_POLICY)
assert ok is True
assert len(findings) == 1  # still detected, just not blocking
```

### Check Output for Sensitive Data

```python
from src.privacy import PrivacyGuard, DEFAULT_PRIVACY_POLICY

answer = "Patient has diabetes and takes metformin"

# Check output
ok, findings = PrivacyGuard.check_output(answer, DEFAULT_PRIVACY_POLICY)

if not ok:
    print("⚠️  Output contains sensitive data")
    for f in findings:
        print(f"  - {f.data_type}: {f.value}")
```

### Process Data According to Policy

```python
from src.privacy import PrivacyGuard, PrivacyPolicy

policy = PrivacyPolicy()
policy.REDACT_PII = True
policy.REDACT_PHI = True

text = "John (SSN 123-45-6789) has diabetes, taking metformin"

# Process input
clean_input = PrivacyGuard.process_input(text, policy)
# Output: "[NAME] (SSN [SSN]) has [MEDICAL], taking [MEDICAL]"

# Process output
clean_output = PrivacyGuard.process_output(text, policy)
# Output: "[NAME] (SSN [SSN]) has [MEDICAL], taking [MEDICAL]"
```

---

## Integration

### In CLI

```bash
python -m src.cli ask "What is my SSN 123-45-6789?" --mode crag
# ❌ ERROR: Input contains sensitive data: ssn
# Query is blocked (PII blocks by default)

python -m src.cli ask "What treatments exist for diabetes?" --mode crag
# ✅ Answered normally — PHI mentions don't block by default (see above)
```

### In API

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What about my credit card 1234-5678-9012-3456?", "mode": "crag"}'
# Response: 400 Bad Request
# "Input contains sensitive data: credit_card"
```

### In Streamlit

```python
try:
    result = run_agent(user_input, selected_mode)
except ValueError as e:
    if "sensitive data" in str(e):
        st.error("❌ Your input contains sensitive information. Please remove it.")
    else:
        st.error(f"Error: {e}")
```

---

## Compliance Standards

### GDPR (General Data Protection Regulation)

**Requirements**:
- Obtain explicit consent before processing
- Provide opt-out mechanism
- Delete data within 30 days on request
- Audit trail for all data access

**Implementation**:
```python
policy = PrivacyPolicy(
    compliance_gdpr=True,
    input_mode=PrivacyMode.REDACT,   # or BLOCK if you must reject rather than mask
    output_mode=PrivacyMode.REDACT,
    log_findings=True,
    data_retention_days=30,
)
```

Erasure and retention are enforced in the database, not just configured here — apply
[`docs/supabase_schema.sql`](supabase_schema.sql) for `purge_expired_chat_messages()`
and `delete_chat_session()`.

### HIPAA (Health Insurance Portability and Accountability Act)

**Requirements**:
- Protect patient medical information
- Minimum necessary principle
- Audit controls
- Access controls

**Implementation**:
```python
policy = PrivacyPolicy()
policy.COMPLIANCE_HIPAA = True
policy.BLOCK_ON_PHI = True
policy.LOG_PHI = True
policy.DATA_RETENTION_DAYS = 7
```

### CCPA (California Consumer Privacy Act)

**Requirements**:
- Consumer right to know about data collection
- Right to delete personal information
- Right to opt-out of sales
- Transparent privacy policy

**Implementation**:
```python
policy = PrivacyPolicy(
    compliance_ccpa=True,
    input_mode=PrivacyMode.REDACT,
    output_mode=PrivacyMode.REDACT,
    log_findings=True,
)
```

---

## Audit Logging

### Log Sensitive Data Findings

```python
import logging

logger = logging.getLogger(__name__)

from src.privacy import PIIDetector, PHIDetector

# Check input
pii_findings = PIIDetector.detect_all(user_input)
phi_findings = PHIDetector.detect_all(user_input)

for f in pii_findings:
    logger.warning(f"PII detected: {f.data_type} at position {f.position}")

for f in phi_findings:
    logger.warning(f"PHI detected: {f.data_type} at position {f.position}")
```

### Compliance Report

```python
from src.privacy import DEFAULT_PRIVACY_POLICY

# Generate compliance report
policy = DEFAULT_PRIVACY_POLICY

report = {
    "policy": "default",
    "input_mode": policy.input_mode.value,
    "output_mode": policy.output_mode.value,
    "detect_phi": policy.detect_phi,
    "log_findings": policy.log_findings,
    "data_retention_days": policy.data_retention_days,
    "compliance_modes": [
        ("GDPR", policy.compliance_gdpr),
        ("HIPAA", policy.compliance_hipaa),
        ("CCPA", policy.compliance_ccpa),
    ]
}

print(report)
```

---

## Testing Privacy

### Test PII Detection

```python
from src.privacy import PIIDetector

test_cases = {
    "ssn": "My SSN is 123-45-6789",
    "email": "Contact me at john@example.com",
    "phone": "Call (555) 123-4567",
    "credit_card": "Card 1234-5678-9012-3456",
    "address": "123 Main St, Springfield, IL 62701",
}

for case, text in test_cases.items():
    findings = PIIDetector.detect_all(text)
    assert len(findings) > 0, f"Failed to detect {case}"
    print(f"✅ {case} detected")
```

### Test PHI Detection

```python
from src.privacy import PHIDetector

test_cases = {
    "condition": "Patient has diabetes",
    "medication": "Taking metformin",
    "procedure": "Underwent surgery",
}

for case, text in test_cases.items():
    findings = PHIDetector.detect_all(text)
    assert len(findings) > 0, f"Failed to detect {case}"
    print(f"✅ {case} detected")
```

### Test Redaction

```python
from src.privacy import DataRedactor

original = "John's SSN is 123-45-6789 and email is john@example.com"
redacted = DataRedactor.redact_all(original)

assert "123-45-6789" not in redacted
assert "john@example.com" not in redacted
assert "[SSN]" in redacted
assert "[EMAIL]" in redacted
print("✅ Redaction works correctly")
```

---

## Best Practices

### 1. **Block Unambiguous PII by Default**
```python
# ✅ Good: PII (SSN, credit card, email) has no legitimate reason to be
# submitted to a chatbot — block it.
policy.BLOCK_ON_PII = True

# PHI is intentionally NOT blocked by default — informational questions about
# medical topics are the expected use case, not a violation. Only enable this
# for deployments that genuinely must reject any medical mention outright.
policy.BLOCK_ON_PHI = False  # set True only if your use case requires it

# ❌ Bad: Allow PII through unchecked
policy.BLOCK_ON_PII = False
```

### 2. **Log for Audit**
```python
# ✅ Good: Log all sensitive data for compliance
policy.LOG_PII = True
policy.LOG_PHI = True

# ❌ Bad: No audit trail
policy.LOG_PII = False
```

### 3. **Short Retention**
```python
# ✅ Good: Minimal data retention
policy.DATA_RETENTION_DAYS = 30

# ❌ Bad: Keep data forever
policy.DATA_RETENTION_DAYS = 365
```

### 4. **Educate Users**
```python
# Show clear error messages
❌ "Your query contains sensitive information. 
   Please do not share:
   - Social Security Numbers
   - Credit Card Numbers
   - Medical Information
   - Passwords or API Keys"
```

### 5. **Comply with Standards**
```python
# Set appropriate compliance mode
if operating_in_europe:
    policy.COMPLIANCE_GDPR = True
    
if handling_healthcare:
    policy.COMPLIANCE_HIPAA = True
    
if operating_in_california:
    policy.COMPLIANCE_CCPA = True
```

---

## Limitations & Considerations

### What It Detects Well
✅ Common PII patterns (SSN, emails, phone numbers)  
✅ Known medications and medical procedures  
✅ Common address formats  

### What It Doesn't Catch
⚠️ Names in unusual formats  
⚠️ Custom or rare medical conditions  
⚠️ Misspelled sensitive terms  
⚠️ Encoded or obfuscated data  

### Manual Review Recommended
Always consider manual review for:
- Healthcare applications (HIPAA compliance)
- Financial systems
- Government data
- Any highly sensitive context

---

## Production Deployment

### Checklist

- [ ] Enable privacy checks in all interfaces (CLI, API, React UI, Streamlit)
- [ ] Set appropriate privacy policy for your use case
- [ ] Configure compliance mode (GDPR/HIPAA/CCPA)
- [ ] Set up audit logging
- [ ] Test with sample sensitive data
- [ ] Document privacy practices
- [ ] Train team on privacy policies
- [ ] Set up data retention cleanup
- [ ] Monitor for false positives/negatives
- [ ] Regular security audits

### Configuration Template

```python
from src.privacy import PrivacyPolicy

# Configure based on your use case
PRIVACY_POLICY = PrivacyPolicy()

# Detection
PRIVACY_POLICY.BLOCK_ON_PII = True
PRIVACY_POLICY.BLOCK_ON_PHI = False  # True only for deployments that must reject any medical mention

# Processing
PRIVACY_POLICY.REDACT_PII = False
PRIVACY_POLICY.REDACT_PHI = False

# Logging
PRIVACY_POLICY.LOG_PII = True
PRIVACY_POLICY.LOG_PHI = True

# Retention
PRIVACY_POLICY.DATA_RETENTION_DAYS = 30

# Compliance
PRIVACY_POLICY.COMPLIANCE_GDPR = True  # If in EU
PRIVACY_POLICY.COMPLIANCE_HIPAA = False  # If healthcare
PRIVACY_POLICY.COMPLIANCE_CCPA = False  # If in California
```

---

## Summary

Privacy protection is **critical**:

✅ **PII Detection** — Blocks sensitive personal data  
✅ **PHI Detection** — Blocks health information  
✅ **Data Redaction** — Removes sensitive data from output  
✅ **Compliance** — Supports GDPR, HIPAA, CCPA  
✅ **Audit Logging** — Tracks all sensitive data access  

**Automatically enforced in all interfaces!**

---

**Protect your users' data!** 🔒🛡️
