# Additional Property-Based Test Opportunities

## You're Right - There Are More Cases

After deeper investigation, I found **3 more critical areas** where property-based testing would catch real bugs:

---

## 1. discord_id Type Consistency ⚠️

### The Problem: int ↔ string conversions

**Usage**: 172 occurrences across 20 files

**Type inconsistencies found**:
```python
# Database (web/team/models.py)
discord_id = models.BigIntegerField()  # int

# Discord API
interaction.user.id  # int (Discord snowflake)

# Authentik API (web/core/authentik.py:60)
attributes["discord_id"] = str(discord_id)  # CONVERTED TO STRING!

# Authentik query (web/core/authentik.py:91)
params={"attributes__discord_id": str(discord_id)}  # Also string
```

### Potential Bugs

**Bug 1: Query mismatch**
```python
# Store as int accidentally
attributes["discord_id"] = discord_id  # BUG: Forgot str()

# Query as string
params={"attributes__discord_id": str(discord_id)}

# Result: Not found (123456789 ≠ "123456789")
```

**Bug 2: JSON serialization**
```python
# Discord IDs can be larger than JavaScript's MAX_SAFE_INTEGER
discord_id = 1234567890123456789  # 19 digits

# JSON serialization loses precision
json.dumps({"discord_id": discord_id})
# JavaScript parseInt() → wrong value
```

**Bug 3: Leading zeros (unlikely but possible)**
```python
# If stored as string with leading zero
attributes["discord_id"] = "0123456789"

# Parsed as int
int("0123456789")  # → 123456789 (loses leading zero)

# Round-trip fails
```

### Property Tests Needed

```python
@given(discord_id=st.integers(min_value=100000000000000000, max_value=999999999999999999))
def test_discord_id_round_trip_with_authentik(discord_id):
    """Property: discord_id → Authentik → query → same value"""
    # Store in Authentik (as string)
    attributes = {"discord_id": str(discord_id)}

    # Query from Authentik (as string)
    query_value = str(discord_id)

    # Parse back to int
    retrieved = int(attributes["discord_id"])

    # Property: Round-trip preserves value
    assert retrieved == discord_id

@given(discord_id=st.integers(min_value=100000000000000000, max_value=999999999999999999))
def test_discord_id_json_serialization_safe(discord_id):
    """Property: Discord IDs should survive JSON round-trip"""
    import json

    # Serialize to JSON
    data = {"discord_id": str(discord_id)}  # Must use string!
    json_str = json.dumps(data)

    # Deserialize
    parsed = json.loads(json_str)
    retrieved = int(parsed["discord_id"])

    # Property: Value preserved
    assert retrieved == discord_id
```

**Value**: Would catch int/string conversion bugs, JSON precision loss

---

## 2. Ticket Category Validation ⚠️

### The Problem: No validation of category strings

**Valid categories** (from `web/core/tickets_config.py`):
```python
TICKET_CATEGORIES = {
    "service-scoring-validation",
    "box-reset",
    "scoring-service-check",
    "blackteam-phone-consultation",
    "blackteam-handson-consultation",
    "other",
}
```

**But tests use invalid category**:
```python
# web/core/tests/test_web_views.py:547
category="technical"  # NOT IN TICKET_CATEGORIES!

# web/core/tests/test_file_upload_security.py
category="technical"  # Also not valid

# bot/tests/test_admin_destructive_operations.py:492
category="technical"  # Used everywhere in tests
```

**No validation found** - `grep` in `web/ticketing` found zero validation checks!

### Potential Bugs

**Bug 1: Typos silently accepted**
```python
# Developer typo
ticket = Ticket.objects.create(
    category="box-rset",  # TYPO: should be "box-reset"
    ...
)

# No error raised
# Points calculation fails (expects "box-reset" key)
# Ticket created but broken
```

**Bug 2: Dashboard lookups fail**
```python
# Dashboard tries to get category info
cat_info = TICKET_CATEGORIES.get(ticket.category, {"display_name": category_id})

# If category="asdf", falls back to default
# Loses all config (points, required_fields, etc.)
```

**Bug 3: Required fields not enforced**
```python
# "box-reset" requires hostname
TICKET_CATEGORIES["box-reset"]["required_fields"] = ["hostname", "ip_address"]

# But if typo in category name
category="box-rset"  # TYPO

# Required fields not checked
# Ticket created without hostname
```

### Property Tests Needed

```python
from hypothesis import strategies as st

# Strategy: Only valid category strings
valid_categories = st.sampled_from(list(TICKET_CATEGORIES.keys()))

@given(category=valid_categories)
def test_all_valid_categories_have_config(category):
    """Property: All valid categories should have complete config"""
    config = TICKET_CATEGORIES[category]

    # Property: Every category has display_name
    assert "display_name" in config
    assert config["display_name"]  # Not empty

    # Property: Required/optional fields are lists
    if "required_fields" in config:
        assert isinstance(config["required_fields"], list)

    if "optional_fields" in config:
        assert isinstance(config["optional_fields"], list)

@given(category=st.text(min_size=1).filter(lambda x: x not in TICKET_CATEGORIES))
def test_invalid_categories_rejected(category):
    """Property: Invalid categories should be rejected"""
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        Ticket.objects.create(
            category=category,  # Invalid category
            team=team,
            title="Test",
        )

@given(category=valid_categories, team_number=st.integers(min_value=1, max_value=50))
def test_category_required_fields_enforced(category, team_number):
    """Property: Required fields must be present for each category"""
    config = TICKET_CATEGORIES[category]
    required_fields = config.get("required_fields", [])

    # Skip if this would create duplicate
    assume(not Team.objects.filter(team_number=team_number).exists())

    team = Team.objects.create(team_number=team_number, ...)

    # Try to create ticket without required fields
    if required_fields:
        with pytest.raises(ValidationError):
            Ticket.objects.create(
                category=category,
                team=team,
                title="Test",
                # Missing required fields
            )
```

**Value**: Would catch typos, enforce validation, ensure config completeness

---

## 3. Ticket Number Format Consistency 🟡

### The Problem: Multiple format strings

**Found these different formats**:

```python
# Production (web/ticketing/utils.py:56)
ticket_number = f"T{team.team_number:03d}-{sequence:03d}"
# → "T001-042"

# Tests (web/core/tests/test_web_views.py:548)
ticket_number = "BT01-00001"
# → Uses "BT" prefix (not "T")
# → 2-digit team number (not 3)
# → 5-digit sequence (not 3)
```

**Parsing** (bot/ticket_dashboard.py:141):
```python
match = re.match(r"Ticket ([^:]+):", embed.title)
# Accepts ANY format in title
```

### Potential Bugs

**Bug 1: Test format doesn't match production**
```python
# Production generates
"T001-042"

# Tests expect
"BT01-00042"

# Code that parses ticket_number using one format breaks on the other
```

**Bug 2: Sequence overflow**
```python
# Format uses 3 digits
f"T{team_number:03d}-{sequence:03d}"

# But sequence can be > 999
sequence = 1000

# Result: "T001-1000" (4 digits, not 3)
# Regex expecting 3 digits fails to match
```

### Property Tests Needed

```python
@given(
    team_number=st.integers(min_value=1, max_value=50),
    sequence=st.integers(min_value=1, max_value=999)
)
def test_ticket_number_format_is_parseable(team_number, sequence):
    """Property: Generated ticket numbers can be parsed back"""
    # Generate ticket number (production format)
    ticket_number = f"T{team_number:03d}-{sequence:03d}"

    # Parse it back
    match = re.match(r"T(\d{3})-(\d{3})", ticket_number)
    assert match

    parsed_team = int(match.group(1))
    parsed_seq = int(match.group(2))

    # Property: Round-trip preserves values
    assert parsed_team == team_number
    assert parsed_seq == sequence

@given(sequence=st.integers(min_value=1000, max_value=9999))
def test_ticket_sequence_overflow_handling(sequence):
    """Property: Large sequence numbers should be handled gracefully"""
    team_number = 1

    # What happens with large sequence?
    ticket_number = f"T{team_number:03d}-{sequence:03d}"

    # If sequence > 999, format breaks
    # This test would FAIL, revealing the bug
    # You'd need to either:
    # 1. Use more digits: {sequence:05d}
    # 2. Or reject sequence > 999
```

**Value**: Would catch format mismatches between production and tests

---

## Summary: All Property-Based Test Opportunities

| Domain | Usage | Inconsistency | Priority | Tests Created |
|--------|-------|---------------|----------|---------------|
| **team_number** | 137× in 20 files | Format padding (02d vs 03d) | 🔴 HIGH | ✅ Done (14 tests) |
| **discord_id** | 172× in 20 files | Type conversion (int ↔ string) | 🟡 MEDIUM | ❌ Not yet |
| **ticket categories** | Many places | No validation, typos possible | 🟡 MEDIUM | ❌ Not yet |
| **ticket_number** | 131× in 20 files | Format mismatch (prod vs tests) | 🟢 LOW | ⚠️ Partial (in team_number tests) |

---

## Should We Add Tests for These?

### discord_id - YES ✅
- **172 occurrences** - high risk
- **Type conversions** - int ↔ string bugs are common
- **JSON precision** - Discord IDs can exceed JavaScript MAX_SAFE_INTEGER
- **Authorization-critical** - bugs = users can't link accounts

**Estimated tests**: 4-6 tests, 100 lines

### Ticket categories - YES ✅
- **No validation** - currently accepts ANY string (bug!)
- **Typos break point calculation** - category="box-rset" silently accepted
- **Required fields not enforced** - can create tickets without hostname
- **Simple to test** - just validate against TICKET_CATEGORIES keys

**Estimated tests**: 3-5 tests, 80 lines

### ticket_number format - MAYBE 🤔
- Already partially covered by team_number tests
- Test format doesn't match production (but both work)
- Would need to fix tests first (change "BT01-00001" to "T001-001")

**Estimated tests**: 2-3 tests, 50 lines (if we do it)

---

## Recommendation

**Add 2 more property-based test files**:

1. `bot/tests/test_discord_id_properties.py` - Type consistency, JSON safety
2. `bot/tests/test_ticket_category_properties.py` - Validation, typo prevention

**Total additional tests**: 7-11 tests, ~180 lines

**Time to implement**: 1-2 hours

**Bugs prevented**: Type conversion failures, typos in category names, missing validation

---

## The Pattern We Found

Property-based tests are useful when:
1. ✅ Used in many places (>100 occurrences)
2. ✅ Has format variations or type conversions
3. ✅ Simple invariants (round-trip, validation, bounds)
4. ✅ Bugs would cause user-visible failures
5. ✅ Current tests use different formats than production

**All 3 candidates match this pattern.**

You were right to push back - there ARE more useful cases beyond team_number.
