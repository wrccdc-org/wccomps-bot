# What's Actually Dangerous? Threat Model Analysis

**Your questions**:
1. "File extensions aren't interesting"
2. "I don't know why mime types are important"
3. "What is dangerous content?"
4. "Why are content-disposition headers important?"

**You're right to ask.** Let me explain what's ACTUALLY dangerous based on how the code works.

---

## How File Upload/Download Actually Works

### Upload (lines 750-796)
```python
def ticket_attachment_upload(request, ticket_id):
    uploaded_file = request.FILES.get("attachment")
    file_data = uploaded_file.read()  # Read bytes

    TicketAttachment.objects.create(
        file_data=file_data,  # Store in DATABASE as BLOB
        filename=uploaded_file.name,
        mime_type=uploaded_file.content_type,
    )
```

### Download (lines 800-820)
```python
def ticket_attachment_download(request, ticket_id, attachment_id):
    attachment = TicketAttachment.objects.get(...)

    response = HttpResponse(
        bytes(attachment.file_data),  # Serve from database
        content_type=attachment.mime_type  # Browser hint
    )
    response["Content-Disposition"] = content_disposition_header(
        as_attachment=True,  # Force download, not display
        filename=attachment.filename
    )
    return response
```

**Key facts**:
- Files stored as BLOBs in PostgreSQL, NOT on filesystem
- No static file serving with direct URLs
- Always served with `Content-Disposition: attachment` (forces download)

---

## Threat Analysis

### 1. File Extensions - **NOT INTERESTING** (You're Right!)

**Your claim**: "File extensions aren't interesting"
**Analysis**: **CORRECT** for this codebase.

**Why extensions DON'T matter here**:
- Files are in database, not filesystem
- No direct URL access like `https://site.com/uploads/malware.exe`
- Server doesn't execute files
- Browser downloads them as-is

**When extensions WOULD matter**:
- If files were saved to disk: `open(f"/uploads/{filename}", "wb")`
- If server executed them: `exec(open(filename).read())`
- If static file serving: `MEDIA_URL = '/media/'`

**This app does none of these. Extension validation is security theater.**

---

### 2. MIME Types - **COMPLICATED**

**Your question**: "I don't know why mime types are important"
**Answer**: It depends on `Content-Disposition`.

#### Scenario A: Content-Disposition: inline (BAD)

```python
response["Content-Disposition"] = "inline; filename=foo.html"
```

Browser **displays** the file inline. MIME type matters:

| MIME Type | What Happens | Danger |
|-----------|--------------|---------|
| `text/html` | Browser renders HTML | **XSS** - scripts execute |
| `image/svg+xml` | Browser renders SVG | **XSS** - SVG can have `<script>` |
| `application/pdf` | Browser shows PDF | Safe (usually) |
| `text/plain` | Browser shows text | Safe |

**Attack**: Upload `<script>alert(document.cookie)</script>` with `Content-Type: text/html` → XSS

#### Scenario B: Content-Disposition: attachment (SAFE)

```python
response["Content-Disposition"] = "attachment; filename=foo.html"
```

Browser **downloads** the file. MIME type doesn't matter much:
- Browser won't execute it
- User has to manually open it
- Runs in user's context, not website's

**Current code uses `as_attachment=True`** → This is safe!

#### So Do MIME Types Matter Here?

**NO, because**:
1. Code uses `Content-Disposition: attachment`
2. Browser downloads, doesn't execute
3. No inline rendering

**HOWEVER**: If code is changed to `as_attachment=False`, instant XSS vulnerability.

**Recommendation**: Validate MIME type anyway as defense-in-depth, or always force `text/plain` / `application/octet-stream` to be safe.

---

### 3. Dangerous Content - **DEPENDS ON CONTEXT**

**Your question**: "What is dangerous content?"
**Answer**: Only dangerous if **executed**.

#### Content That's Dangerous IF Rendered Inline:

1. **HTML with JavaScript**
   ```html
   <script>
   fetch('/api/change-password', {
     method: 'POST',
     body: JSON.stringify({new_password: 'hacked'})
   })
   </script>
   ```
   - Dangerous if: `Content-Type: text/html` + `Content-Disposition: inline`
   - Safe if: Downloaded as attachment

2. **SVG with JavaScript**
   ```xml
   <svg xmlns="http://www.w3.org/2000/svg">
     <script>alert(document.cookie)</script>
   </svg>
   ```
   - Dangerous if: `Content-Type: image/svg+xml` + `Content-Disposition: inline`
   - Safe if: Downloaded as attachment

3. **PDF with JavaScript** (yes, PDFs can have JS)
   - Rare attack
   - Safe if downloaded

#### Content That's NOT Dangerous (in this context):

1. **Executable files (.exe, .sh, .bat)**
   - Server doesn't execute them
   - Just bytes in database
   - User has to download AND run them
   - That's user's problem, not XSS

2. **PHP/Python/Java files**
   - Server doesn't execute them
   - Just text/bytes
   - No danger to server

**In this codebase**: Nothing is dangerous because `Content-Disposition: attachment` prevents execution.

**BUT**: If someone changes to inline rendering, HTML/SVG become XSS vectors.

---

### 4. Content-Disposition Headers - **CRITICAL FOR SECURITY**

**Your question**: "Why are content-disposition headers important?"
**Answer**: They tell the browser "download this" vs "display this"

#### Content-Disposition: attachment (Current code - SAFE)

```http
Content-Disposition: attachment; filename="user-upload.html"
```

- Browser downloads the file
- Browser does NOT execute it
- User sees "Save file" dialog
- **Result**: No XSS, even if file contains scripts

#### Content-Disposition: inline (NOT used - would be DANGEROUS)

```http
Content-Disposition: inline; filename="user-upload.html"
```

- Browser displays the file **in the page**
- Browser executes any scripts
- **Result**: XSS vulnerability

#### Header Injection Attack

**Attack**: If filename contains `\r\n`, inject headers:
```
filename="foo.txt\r\nX-XSS-Protection: 0\r\nContent-Type: text/html\r\n\r\n<script>alert(1)</script>"
```

**Result**: Could inject arbitrary HTTP headers or body

**Protection**: Django's `content_disposition_header()` escapes this. **Already safe.**

---

## What's ACTUALLY Vulnerable

### Real Bug #1: Client-Side Path Traversal (MEDIUM Risk)

**Code**:
```python
filename=uploaded_file.name  # Could be "../../../.bashrc"
```

**Attack**: Upload file named `../../../.bashrc`

**What happens**:
1. Filename stored in database: `../../../.bashrc`
2. User downloads file
3. Browser saves to: `Downloads/../../../.bashrc`
4. On some OS/browsers, file writes outside Downloads folder
5. Could overwrite `/home/user/.bashrc`, `/etc/hosts`, etc.

**This is REAL**. Not server compromise, but client compromise.

**Fix**: Sanitize filename to just basename:
```python
import os
safe_filename = os.path.basename(uploaded_file.name)
```

### Real Bug #2: Stored XSS IF Code Changes (MEDIUM-HIGH Risk)

**Current code**: Safe because `as_attachment=True`

**If someone changes** to `as_attachment=False`:
```python
response["Content-Disposition"] = content_disposition_header(
    as_attachment=False,  # OOPS
    filename=attachment.filename
)
```

**Attack**: Upload HTML with JavaScript → XSS

**Fix**: Force safe MIME type:
```python
safe_mime_types = {'image/png', 'image/jpeg', 'application/pdf', 'text/plain'}
if attachment.mime_type not in safe_mime_types:
    content_type = 'application/octet-stream'  # Force download
else:
    content_type = attachment.mime_type
```

**Or**: Always use `application/octet-stream`:
```python
response = HttpResponse(
    bytes(attachment.file_data),
    content_type='application/octet-stream'  # Browser will download, not execute
)
```

---

## What's Security Theater

### 1. File Extension Validation ❌

**Proposed**: Block `.exe`, `.sh`, `.php`

**Why it doesn't help**:
- Server doesn't execute files
- Files in database, not filesystem
- User can upload `malware.txt` and rename locally to `malware.exe`
- Attacker cares about XSS, not about uploading .exe

**Verdict**: Security theater. Wastes time.

### 2. MIME Type Validation (Current Code) ❌

**Proposed**: Validate `Content-Type` matches file content

**Why it doesn't help right now**:
- `Content-Disposition: attachment` prevents execution
- MIME type only used as hint
- Browser won't execute downloaded files

**Verdict**: Defense-in-depth, but not critical with current code.

---

## What Actually Matters

### Priority 1: Filename Sanitization ✅ CRITICAL

**Fix**:
```python
import os
safe_filename = os.path.basename(uploaded_file.name)
safe_filename = safe_filename.replace('\x00', '')  # Remove null bytes
if not safe_filename or safe_filename.startswith('.'):
    safe_filename = 'attachment.bin'
```

**Impact**: Prevents client-side path traversal

### Priority 2: Hardcode Safe Content-Type ✅ RECOMMENDED

**Fix**:
```python
response = HttpResponse(
    bytes(attachment.file_data),
    content_type='application/octet-stream'  # Always safe
)
```

**Impact**: Future-proof against someone changing `as_attachment=False`

### Priority 3: Code Review Alert ✅ RECOMMENDED

**Add comment**:
```python
# SECURITY: as_attachment=True is CRITICAL. Never change to False without
# comprehensive MIME type validation, or you'll introduce XSS.
response["Content-Disposition"] = content_disposition_header(
    as_attachment=True,  # DO NOT CHANGE
    filename=safe_filename
)
```

---

## Summary

**Your intuitions were correct**:

1. ✅ **File extensions**: NOT interesting for this codebase (files in DB, not executed)
2. ⚠️ **MIME types**: Important IF rendered inline, safe with attachment mode
3. ⚠️ **Dangerous content**: Only dangerous if executed/rendered, current code downloads
4. ✅ **Content-Disposition**: CRITICAL - `attachment` = safe, `inline` = XSS

**Actual bugs**:
1. **Path traversal in filename** - Could write client-side files outside Downloads
2. **Future XSS risk** - If someone changes `as_attachment=False`

**Security theater**:
1. File extension validation - Doesn't help
2. MIME type validation - Nice-to-have but not critical with current code

**Fixes needed**:
1. Sanitize filename (basename only)
2. Optionally: Force `application/octet-stream`
3. Add code comment warning about `as_attachment=True`

**NOT needed**:
1. Extension whitelist
2. MIME type content detection
3. Virus scanning (out of scope for this threat model)
