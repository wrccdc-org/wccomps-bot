# Security Analysis - Potential Issues Found

**Analysis Date**: 2025-11-23
**Analyst**: Claude (Code Analysis)
**Scope**: WCComps Discord Bot & WebUI

---

## Summary

Analyzed core security-sensitive code paths in `web/core/views.py`. Found **4 potential security issues** in file upload handling that should be addressed.

**Overall Assessment**: Code is generally well-written with good practices (parameterized queries, login required decorators, team isolation), but file upload security needs improvement.

---

## Findings

### 🔴 HIGH: Filename Not Sanitized (Path Traversal Risk)

**Location**: `web/core/views.py:789`

**Code**:
```python
TicketAttachment.objects.create(
    ticket=ticket,
    file_data=file_data,
    filename=uploaded_file.name,  # ← ISSUE: Not sanitized
    mime_type=uploaded_file.content_type or "application/octet-stream",
    uploaded_by=authentik_username,
)
```

**Issue**: User-supplied filename is stored without sanitization.

**Attack Vector**:
- User uploads file with filename: `../../../etc/passwd`
- If filename is later used in file operations, could enable path traversal

**Recommendation**:
```python
import os
safe_filename = os.path.basename(uploaded_file.name)  # Remove path components
# Or use Django's get_valid_filename:
from django.utils.text import get_valid_filename
safe_filename = get_valid_filename(uploaded_file.name)
```

**Severity**: HIGH (if filename used in file operations later)
**Exploitability**: Medium (depends on how filename is used downstream)

---

### 🟡 MEDIUM: No File Extension Validation

**Location**: `web/core/views.py:750-796`

**Issue**: No validation of file extensions. Users can upload any file type including executables.

**Attack Vector**:
- Upload `malware.exe`, `webshell.php`, `script.sh`
- If these files are ever served or executed, security breach

**Current Protection**:
- Files stored as binary data in database (good!)
- Content-Disposition: attachment header (prevents inline execution)

**Recommendation**:
```python
ALLOWED_EXTENSIONS = {'.txt', '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.doc', '.docx', '.log'}
file_ext = os.path.splitext(uploaded_file.name)[1].lower()

if file_ext not in ALLOWED_EXTENSIONS:
    return HttpResponse(f"File type {file_ext} not allowed", status=400)
```

**Severity**: MEDIUM (mitigated by database storage and Content-Disposition header)

---

### 🟡 MEDIUM: No MIME Type Validation

**Location**: `web/core/views.py:790`

**Code**:
```python
mime_type=uploaded_file.content_type or "application/octet-stream",
```

**Issue**: MIME type from browser is trusted without validation.

**Attack Vector**:
- User uploads `malware.exe` but sets Content-Type: `image/png`
- MIME type stored incorrectly in database
- Could bypass client-side filtering

**Recommendation**:
```python
import magic  # python-magic library
actual_mime = magic.from_buffer(file_data[:2048], mime=True)

# Validate against expected types
ALLOWED_MIMES = {'image/png', 'image/jpeg', 'application/pdf', 'text/plain'}
if actual_mime not in ALLOWED_MIMES:
    return HttpResponse(f"File type {actual_mime} not allowed", status=400)
```

**Severity**: MEDIUM

---

### 🟢 LOW: Content-Disposition Header Injection (Theoretical)

**Location**: `web/core/views.py:819`

**Code**:
```python
response["Content-Disposition"] = str(content_disposition_header(
    as_attachment=True,
    filename=attachment.filename  # ← Could contain special chars
))
```

**Issue**: If filename contains quotes or special characters, could theoretically break out of header.

**Current Protection**: Django's `content_disposition_header()` likely handles escaping

**Recommendation**: Verify Django properly escapes, or sanitize filename on storage (see first issue)

**Severity**: LOW (Django likely handles this correctly)

---

## Good Security Practices Found ✅

1. **Parameterized Queries**: All database queries use Django ORM (no SQL injection)
2. **Authentication Required**: All sensitive views have `@login_required`
3. **Authorization Checks**: Team isolation properly enforced (lines 765, 813)
4. **CSRF Protection**: Django middleware handles CSRF tokens
5. **File Size Limits**: 10MB limit enforced (line 775)
6. **Rate Limiting**: Comment rate limits implemented (line 493)
7. **Token Expiration**: Link tokens expire after 15 minutes (line 152)
8. **Session Management**: Uses Django's secure session framework

---

## Code Quality Observations

**Strengths**:
- Clean, readable code
- Good error handling with user-friendly messages
- Comprehensive logging
- Type hints throughout
- Transaction safety for critical operations

**Minor Issues**:
- Some code duplication between team and ops views
- Long functions (could be refactored into smaller helpers)

---

## Recommendations Priority

1. **IMMEDIATE**: Sanitize filenames on upload (HIGH severity)
2. **SOON**: Add file extension whitelist (MEDIUM severity)
3. **SOON**: Validate MIME types against actual file content (MEDIUM severity)
4. **MONITOR**: Verify Django's Content-Disposition escaping (LOW severity)

---

## Test Coverage Analysis

**Unit Tests**: 260 tests, all passing ✅
- Good coverage of business logic
- Strong property-based testing with Hypothesis
- Async testing patterns

**What Tests Missed**:
- File upload security edge cases
- Filename sanitization
- MIME type validation
- File extension checks

**Recommendation**: Add security-specific tests for file upload:
```python
def test_path_traversal_filename_rejected():
    filename = "../../../etc/passwd"
    # Should either reject or sanitize to "passwd"

def test_executable_file_rejected():
    # Upload .exe, .sh, .php files
    # Should be rejected
```

---

## Conclusion

**Overall Security Posture**: GOOD with room for improvement

The codebase demonstrates good security practices in most areas (authentication, authorization, SQL injection prevention). The main area needing attention is **file upload security**.

**Risk Level**: MEDIUM
- Current risks are mostly theoretical due to good defensive practices (database storage, Content-Disposition headers)
- But best practice is defense-in-depth - should implement filename sanitization regardless

**Next Steps**:
1. Implement filename sanitization
2. Add file extension whitelist
3. Consider MIME type validation
4. Add security tests for file uploads
