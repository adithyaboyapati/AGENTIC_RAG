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
| **SSN** | XXX-XX-XXXX or XXXXXXXXX | 123-45-6789 |
| **Credit Card** | 4 groups of 4 digits | 1234-5678-9012-3456 |
| **Email** | user@domain.com | john@example.com |
| **Phone** | (123) 456-7890 or similar | (555) 123-4567 |
| **Address** | Street address with city/state | 123 Main St, Springfield |
| **Passport** | 1-2 letters + 6-9 digits | AB123456 |
| **Driver License** | 2 letters + 7-8 digits | CA1234567 |

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

```python
from src.privacy import PrivacyPolicy

policy = PrivacyPolicy()

# Detection settings
policy.BLOCK_ON_PII = True         # Block queries with PII
policy.BLOCK_ON_PHI = True         # Block queries with PHI

# Processing settings
policy.REDACT_PII = False          # Remove PII from output
policy.REDACT_PHI = False          # Remove PHI from output

# Logging settings
policy.LOG_PII = True              # Log PII findings for audit
policy.LOG_PHI = True              # Log PHI findings for audit

# Data retention
policy.DATA_RETENTION_DAYS = 30    # Keep data for 30 days

# Compliance modes
policy.COMPLIANCE_GDPR = False     # Enable GDPR mode
policy.COMPLIANCE_HIPAA = False    # Enable HIPAA mode
policy.COMPLIANCE_CCPA = False     # Enable CCPA mode
```

### Custom Policies

```python
from src.privacy import PrivacyPolicy

# Healthcare (HIPAA)
healthcare_policy = PrivacyPolicy()
healthcare_policy.BLOCK_ON_PHI = True
healthcare_policy.LOG_PHI = True
healthcare_policy.DATA_RETENTION_DAYS = 7  # Shorter retention
healthcare_policy.COMPLIANCE_HIPAA = True

# European users (GDPR)
gdpr_policy = PrivacyPolicy()
gdpr_policy.BLOCK_ON_PII = True
gdpr_policy.REDACT_PII = True
gdpr_policy.DATA_RETENTION_DAYS = 30
gdpr_policy.COMPLIANCE_GDPR = True

# California users (CCPA)
ccpa_policy = PrivacyPolicy()
ccpa_policy.BLOCK_ON_PII = True
ccpa_policy.LOG_PII = True
ccpa_policy.COMPLIANCE_CCPA = True
```

---

## Privacy Guard

### Check Input for Sensitive Data

```python
from src.privacy import PrivacyGuard, DEFAULT_PRIVACY_POLICY

question = "My SSN is 123-45-6789"

# Check according to policy
ok, findings = PrivacyGuard.check_input(question, DEFAULT_PRIVACY_POLICY)

if not ok:
    print("❌ Input contains sensitive data:")
    for f in findings:
        print(f"  - {f.data_type}: {f.value}")
else:
    print("✅ Input is safe")
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
# Query is blocked
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
policy = PrivacyPolicy()
policy.COMPLIANCE_GDPR = True
policy.BLOCK_ON_PII = True
policy.LOG_PII = True
policy.DATA_RETENTION_DAYS = 30
```

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
policy = PrivacyPolicy()
policy.COMPLIANCE_CCPA = True
policy.BLOCK_ON_PII = True
policy.LOG_PII = True
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
    "block_pii": policy.BLOCK_ON_PII,
    "block_phi": policy.BLOCK_ON_PHI,
    "redact_pii": policy.REDACT_PII,
    "redact_phi": policy.REDACT_PHI,
    "log_sensitive_data": policy.LOG_PII or policy.LOG_PHI,
    "data_retention_days": policy.DATA_RETENTION_DAYS,
    "compliance_modes": [
        ("GDPR", policy.COMPLIANCE_GDPR),
        ("HIPAA", policy.COMPLIANCE_HIPAA),
        ("CCPA", policy.COMPLIANCE_CCPA),
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

### 1. **Block by Default**
```python
# ✅ Good: Block sensitive data unless explicitly allowed
policy.BLOCK_ON_PII = True
policy.BLOCK_ON_PHI = True

# ❌ Bad: Allow sensitive data
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

- [ ] Enable privacy checks in all interfaces (CLI, API, Streamlit)
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
PRIVACY_POLICY.BLOCK_ON_PHI = True

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
