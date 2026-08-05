# Privacy & Compliance Quick Reference

**Status**: ✅ **ENABLED** — Automatic PII/PHI detection and protection

---

## What Gets Detected & Blocked

### PII (Personally Identifiable Information)
- **SSN**: 123-45-6789 ❌ BLOCKED
- **Credit Card**: 1234-5678-9012-3456 ❌ BLOCKED
- **Email**: john@example.com ❌ BLOCKED
- **Phone**: (555) 123-4567 ❌ BLOCKED
- **Address**: 123 Main St, Springfield ❌ BLOCKED
- **Passport**: AB123456 ❌ BLOCKED
- **Driver License**: CA1234567 ❌ BLOCKED

### PHI (Protected Health Information)
- **Medical Conditions**: diabetes, cancer, covid ❌ BLOCKED
- **Medications**: metformin, aspirin, lisinopril ❌ BLOCKED
- **Procedures**: surgery, chemotherapy, vaccination ❌ BLOCKED
- **Insurance ID**: AB12345678 ❌ BLOCKED

---

## Default Behavior

**Input**: ❌ Block if contains PII or PHI  
**Output**: ⚠️ Warn if contains PII or PHI  
**Logging**: ✅ Log findings for compliance  
**Redaction**: ❌ Don't redact (preserve answer quality)  

---

## Quick Examples

### Test PII Detection
```python
from src.privacy import PIIDetector

text = "Call 555-123-4567 or email john@example.com"
findings = PIIDetector.detect_all(text)
# Returns: 2 findings (phone + email)
```

### Test PHI Detection
```python
from src.privacy import PHIDetector

text = "Patient with diabetes taking metformin"
findings = PHIDetector.detect_all(text)
# Returns: 2 findings (condition + medication)
```

### Redact Sensitive Data
```python
from src.privacy import DataRedactor

text = "Call 555-123-4567"
redacted = DataRedactor.redact_pii(text)
# Returns: "Call [PHONE]"
```

### Mask Values
```python
from src.privacy import DataRedactor

card = "1234567890123456"
masked = DataRedactor.mask_value(card, reveal_chars=4)
# Returns: "************3456"
```

### Configure Privacy Policy
```python
from src.privacy import PrivacyPolicy

policy = PrivacyPolicy()
policy.BLOCK_ON_PII = True          # Block PII
policy.BLOCK_ON_PHI = True          # Block PHI
policy.LOG_PII = True               # Log findings
policy.COMPLIANCE_GDPR = True       # Enable GDPR
```

---

## Usage in Your System

### Automatic in All Interfaces

**CLI**:
```bash
python -m src.cli ask "My SSN is 123-45-6789" --mode crag
# ❌ ERROR: Input contains sensitive data: ssn
```

**API**:
```bash
curl -X POST http://localhost:8000/query \
  -d '{"question": "My credit card is 1234-5678-9012-3456"}'
# 400 Bad Request: Input contains sensitive data
```

**Streamlit**:
```
User enters: "I have diabetes and take metformin"
❌ ERROR: Input contains sensitive data: medical
```

---

## Compliance Modes

### GDPR (European)
```python
policy.COMPLIANCE_GDPR = True
policy.BLOCK_ON_PII = True
policy.LOG_PII = True
policy.DATA_RETENTION_DAYS = 30
```

### HIPAA (Healthcare)
```python
policy.COMPLIANCE_HIPAA = True
policy.BLOCK_ON_PHI = True
policy.LOG_PHI = True
policy.DATA_RETENTION_DAYS = 7
```

### CCPA (California)
```python
policy.COMPLIANCE_CCPA = True
policy.BLOCK_ON_PII = True
policy.LOG_PII = True
```

---

## Policy Configuration

### Production (Strict)
```python
BLOCK_ON_PII = True          # Block PII
BLOCK_ON_PHI = True          # Block PHI
REDACT_PII = False           # Keep full answer
REDACT_PHI = False           # Keep full answer
LOG_PII = True               # Audit trail
LOG_PHI = True               # Audit trail
DATA_RETENTION_DAYS = 30     # Limited retention
```

### Development (Relaxed)
```python
BLOCK_ON_PII = False         # Allow PII
BLOCK_ON_PHI = False         # Allow PHI
REDACT_PII = False           # Keep full answer
REDACT_PHI = False           # Keep full answer
LOG_PII = True               # Still log
LOG_PHI = True               # Still log
```

---

## Redaction Masks

| Data Type | Original | Redacted |
|-----------|----------|----------|
| SSN | 123-45-6789 | [SSN] |
| Email | john@example.com | [EMAIL] |
| Phone | (555) 123-4567 | [PHONE] |
| Credit Card | 1234-5678-9012-3456 | [CREDIT_CARD] |
| Address | 123 Main St | [ADDRESS] |
| Medical | diabetes | [MEDICAL] |

---

## Common Commands

```bash
# Test PII detection
python -c "
from src.privacy import PIIDetector
text = 'Email: john@example.com, Phone: 555-123-4567'
findings = PIIDetector.detect_all(text)
print(f'Found {len(findings)} PII items')
"

# Test PHI detection
python -c "
from src.privacy import PHIDetector
text = 'Patient with diabetes taking metformin'
findings = PHIDetector.detect_all(text)
print(f'Found {len(findings)} PHI items')
"

# Test redaction
python -c "
from src.privacy import DataRedactor
text = 'Email: john@example.com'
redacted = DataRedactor.redact_pii(text)
print(redacted)
"

# Check current policy
python -c "
from src.privacy import DEFAULT_PRIVACY_POLICY
print(f'Block PII: {DEFAULT_PRIVACY_POLICY.BLOCK_ON_PII}')
print(f'Block PHI: {DEFAULT_PRIVACY_POLICY.BLOCK_ON_PHI}')
print(f'Log PII: {DEFAULT_PRIVACY_POLICY.LOG_PII}')
"
```

---

## Files

| File | Purpose |
|------|---------|
| `src/privacy.py` | Core privacy implementation |
| `docs/PRIVACY_COMPLIANCE.md` | Comprehensive guide |
| `PRIVACY_QUICK_REFERENCE.md` | This file |
| `src/runner.py` | Integration point |

---

## What's Detected

### PII Patterns
- ✅ Social Security Numbers (XXX-XX-XXXX)
- ✅ Credit cards (4 x 4 digits)
- ✅ Email addresses
- ✅ Phone numbers (multiple formats)
- ✅ Physical addresses
- ✅ Passport numbers
- ✅ Driver licenses

### PHI Patterns
- ✅ Medical conditions (list of 12+ common conditions)
- ✅ Medical procedures (list of 8+ common procedures)
- ✅ Medications (common prescription drugs)
- ✅ Insurance IDs

---

## What's NOT Detected

⚠️ Names in unusual formats  
⚠️ Custom medical terms  
⚠️ Misspelled sensitive terms  
⚠️ Encoded/obfuscated data  
⚠️ Very old SSN formats  

**Manual review recommended** for high-security contexts!

---

## Integration with Other Guardrails

```
User Input
    ↓
[Privacy Check] ← Detects PII/PHI, blocks if needed
    ↓
[Input Guardrails] ← Validates length, keywords
    ↓
[Agent Processing]
    ↓
[Output Guardrails] ← Checks quality, length
    ↓
[Privacy Check] ← Detects PII/PHI in output, warns
    ↓
User Response
```

---

## Production Checklist

- [ ] Privacy checks enabled in all interfaces
- [ ] Appropriate compliance mode configured (GDPR/HIPAA/CCPA)
- [ ] Audit logging enabled
- [ ] Data retention policy set
- [ ] Team trained on privacy policies
- [ ] User-facing documentation updated
- [ ] Privacy policy posted online
- [ ] Regular security audits scheduled
- [ ] False positive/negative monitoring

---

## Key Numbers

| Metric | Value |
|--------|-------|
| PII Types Detected | 7 |
| PHI Types Detected | 4 |
| Data Retention Default | 30 days |
| Compliance Standards | GDPR, HIPAA, CCPA |
| Block on PII (default) | ✅ Enabled |
| Block on PHI (default) | ✅ Enabled |

---

## Summary

**Privacy protection is built-in:**

✅ **Automatic Detection** — PII & PHI detected automatically  
✅ **Blocking** — Prevents sensitive data from being processed  
✅ **Redaction** — Can remove sensitive data if configured  
✅ **Logging** — Audit trail for compliance  
✅ **Compliance** — Supports GDPR, HIPAA, CCPA  
✅ **No Configuration Needed** — Works out of the box  

---

**Your system is privacy-protected!** 🔒🛡️
