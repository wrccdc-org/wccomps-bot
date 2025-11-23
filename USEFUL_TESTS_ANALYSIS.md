# What Makes Tests Actually Useful?

**Date**: 2025-11-23
**Purpose**: Document the difference between USEFUL tests and USELESS tests

---

## Lessons Learned from Critical Analysis

After analyzing our tests critically, I learned:
1. **Passing tests ≠ useful tests**
2. **Testing tautologies finds zero bugs**
3. **Testing the database/framework doesn't test our code**
4. **Weak assertions accept any failure**
5. **Real bugs come from edge cases, race conditions, and security vulnerabilities**

---

## Old Tests vs New Tests - Side by Side Comparison

### Example 1: Rate Limiting

**OLD TEST (Tautology)**:
```python
def test_rate_limit_property(self, attempts: int):
    """Property: rate limit allows iff attempts < 5 in last hour."""

    # Create attempts
    for _i in range(attempts):
        LinkRateLimit.objects.create(discord_id=discord_id)

    is_allowed, attempt_count = LinkRateLimit.check_rate_limit(discord_id)

    # TEST: Verify the function returns what it's defined to return
    assert is_allowed == (attempts < 5)
    assert attempt_count == attempts
```

**Why this is useless**:
- Tests the DEFINITION of rate limiting
- Implementation: `return attempts < 5`
- Test: `assert is_allowed == (attempts < 5)`
- This is testing that `==` works in Python
- **Bugs found**: 0
- **Could find bugs**: No

**NEW TEST (Attack Vector)**:
```python
async def test_rapid_link_attempts_cannot_bypass_rate_limit(self):
    """
    SCENARIO: User makes 10 link attempts rapidly (within milliseconds).

    PROPERTY: Should be blocked after 5 attempts.
    BUG IF: More than 5 attempts succeed (race condition).
    """

    async def attempt_link(attempt_num):
        is_allowed, count = LinkRateLimit.check_rate_limit(discord_id)
        if is_allowed:
            await LinkRateLimit.objects.acreate(discord_id=discord_id)
            return "allowed"
        return "blocked"

    # Make 10 CONCURRENT attempts
    results = await asyncio.gather(*[
        attempt_link(i) for i in range(10)
    ])

    allowed_count = sum(1 for r in results if r == "allowed")

    # CRITICAL: Check if race condition bypassed limit
    assert allowed_count <= 5, (
        f"RACE CONDITION BUG: Rate limit bypassed! "
        f"Expected: ≤5, Got: {allowed_count}"
    )
```

**Why this is useful**:
- Tests REAL bug: race condition in rate limit check
- Tests with CONCURRENT requests (like production)
- Tests if check-then-create is atomic
- **Could find bugs**: Yes - race conditions
- **Would fail if**: check_rate_limit and create are not in a transaction

---

### Example 2: Team Member Count

**OLD TEST (Tautology)**:
```python
def test_member_count_never_negative(self, max_members: int, team_number: int):
    """Property: get_member_count() is always >= 0."""

    team = Team.objects.create(
        team_number=team_number,
        team_name=f"Team {team_number}",
        max_members=max_members,
    )

    assert team.get_member_count() >= 0
```

**Why this is useless**:
- SQL COUNT() cannot return negative
- Tests that PostgreSQL works
- **Bugs found**: 0
- **Could find bugs**: Only if PostgreSQL is broken

**NEW TEST (Actual Bug Scenario)**:
```python
async def test_concurrent_joins_to_almost_full_team(self):
    """
    SCENARIO: Team has max_members=5, currently has 4 members.
    Two users try to join simultaneously.

    PROPERTY: Exactly one should succeed, team should have exactly 5 members.
    BUG IF: Team ends up with 6 members (both succeeded).
    """

    # Create team with 4/5 members
    team = await Team.objects.acreate(max_members=5)
    for i in range(4):
        await DiscordLink.objects.acreate(team=team, ...)

    # Two users join AT THE SAME TIME
    results = await asyncio.gather(
        try_join_team(user1),
        try_join_team(user2),
    )

    # CRITICAL: Team should NOT have 6 members
    final_count = await team.aget_member_count()
    assert final_count <= 5, (
        f"RACE CONDITION BUG: Team exceeded max_members! Got: {final_count}"
    )
```

**Why this is useful**:
- Tests REAL bug: two users joining when 1 slot left
- Tests if is_full() check is atomic
- Tests the actual business logic, not SQL
- **Could find bugs**: Yes - if check isn't in SELECT FOR UPDATE
- **Would fail if**: No database locking on member count

---

### Example 3: File Upload Security

**OLD TEST (None - 0% coverage)**:
```python
# File upload had 0% coverage
# 4 security bugs found via code review
```

**NEW TEST (Actual Attack)**:
```python
def test_filename_with_path_traversal_should_be_rejected(self):
    """
    ATTACK: Upload file with '../../../etc/passwd' as filename.

    EXPECTED: Filename should be sanitized to 'passwd' or rejected.
    CURRENT: Likely accepted as-is (BUG).
    """

    # Malicious filename
    malicious_filename = "../../../etc/passwd"
    uploaded_file = SimpleUploadedFile(
        name=malicious_filename,
        content=b"malicious content",
    )

    response = ticket_attachment_upload(request, ticket.id)

    if response.status_code == 200:
        attachment = TicketAttachment.objects.get(ticket=ticket)

        # CRITICAL: Filename should NOT contain path traversal
        assert ".." not in attachment.filename, (
            f"SECURITY BUG: Path traversal in filename! "
            f"Got: {attachment.filename}"
        )
        assert "/" not in attachment.filename, (
            f"SECURITY BUG: Directory separator in filename!"
        )
```

**Why this is useful**:
- Tests ACTUAL attack vector
- Tests with MALICIOUS input (not happy path)
- Strong assertion: verifies WHAT we reject and WHY
- **Could find bugs**: Yes - found 4 bugs in code review
- **Would fail if**: Filename not sanitized (which it isn't)

---

### Example 4: Admin Destructive Operations

**OLD TEST (None - 0% coverage)**:
```python
# admin_competition.py: NEVER IMPORTED during tests
# 888 lines of destructive operations with 0 tests
```

**NEW TEST (Safety Check)**:
```python
async def test_end_competition_only_deactivates_team_links(self):
    """
    CRITICAL: Should deactivate team member links, NOT admin/support links.

    BUG IF: Admin/support accounts are deactivated.
    """

    # Create team links
    team_link = await DiscordLink.objects.acreate(team=team1, ...)

    # Create admin links (should NOT be touched)
    admin_link = await DiscordLink.objects.acreate(team=None, ...)  # No team

    # Call end_competition
    await cog.admin_end_competition(interaction)

    # CRITICAL: Verify team links deactivated
    await team_link.arefresh_from_db()
    assert not team_link.is_active, "Team link should be deactivated"

    # CRITICAL: Verify admin links NOT deactivated
    await admin_link.arefresh_from_db()
    assert admin_link.is_active, (
        f"BUG: Admin link was deactivated! "
        f"discord_id={admin_link.discord_id}"
    )
```

**Why this is useful**:
- Tests CRITICAL safety requirement
- Tests that we don't delete/deactivate wrong things
- Tests the ACTUAL code path (imports the module!)
- **Could find bugs**: Yes - logic errors in filtering
- **Would fail if**: Filter is `team__isnull=False` vs `team__isnull=True`

---

## Principles for Useful Tests

### 1. Test Attack Vectors, Not Definitions

**BAD**:
```python
assert is_full() == (count >= max)  # Definition of is_full
```

**GOOD**:
```python
# Upload file with '../../../etc/passwd'
assert ".." not in saved_filename  # Security requirement
```

### 2. Test Concurrent Operations, Not Sequential

**BAD**:
```python
for i in range(5):
    add_member(team, user_i)
assert team.count() == 5
```

**GOOD**:
```python
results = await asyncio.gather(*[
    add_member(team, user) for user in 5_users
])
assert team.count() <= max_members  # Check race condition
```

### 3. Test Error Paths, Not Just Happy Paths

**BAD**:
```python
ticket = create_ticket(...)
assert ticket.status == "open"
```

**GOOD**:
```python
try:
    with transaction.atomic():
        create_ticket(...)
        raise Exception("Simulate failure")
except:
    pass

# Verify rollback - no orphaned records
assert Ticket.objects.count() == initial_count
```

### 4. Test Authorization, Not Just Functionality

**BAD**:
```python
attachment = download_attachment(attachment_id)
assert attachment.file_data == expected_data
```

**GOOD**:
```python
# Team 2 user tries to download Team 1's file
response = download_attachment(attachment_id, user=team2_user)
assert response.status_code in [403, 404], (
    "SECURITY BUG: Cross-team access allowed!"
)
```

### 5. Test Realistic Malicious Input

**BAD**:
```python
try:
    create_link(discord_id=-1)
except Exception:
    pass  # Any exception is fine
```

**GOOD**:
```python
malicious_inputs = [
    "../../../etc/passwd",           # Path traversal
    "file.pdf\x00.exe",              # Null byte injection
    'file"\r\nX-Evil: injected\r\n', # Header injection
]

for malicious in malicious_inputs:
    upload_file(malicious)
    assert malicious not in saved_filename, (
        f"SECURITY BUG: {malicious} not sanitized!"
    )
```

### 6. Strong Assertions That Explain WHY

**BAD**:
```python
assert result is not None
```

**GOOD**:
```python
assert result.status == "deactivated", (
    f"BUG: Admin account still active after end_competition! "
    f"discord_id={admin.discord_id}, username={admin.username}"
)
```

### 7. Test Properties That Actually Matter

**BAD** (Tautology):
```python
assert is_expired() == (now > expires_at)  # This is the definition
```

**GOOD** (Invariant):
```python
# After ANY sequence of operations:
assert team.get_member_count() <= team.max_members
assert team.get_member_count() >= 0
assert team.get_member_count() == DiscordLink.objects.filter(
    team=team, is_active=True
).count()  # Count must match database
```

---

## Test Coverage Comparison

### Old Tests

| Coverage Area | Tests | Bugs Found | Value |
|--------------|-------|------------|-------|
| Property-based tautologies | 22 | 0 | LOW |
| Web views | 0 | Unknown (4 found manually) | ZERO |
| Admin commands | 0 | Unknown | ZERO |
| Concurrent operations | 6 | 0 | LOW |
| Security attacks | 0 | Unknown (4 found manually) | ZERO |
| **Total** | **260** | **0** | **LOW** |

### New Tests

| Coverage Area | Tests | Could Find | Value |
|--------------|-------|------------|-------|
| File upload security | 20+ | Path traversal, executable uploads, XSS, header injection | HIGH |
| Race conditions | 10+ | Team overfill, rate limit bypass, lost updates | HIGH |
| Admin safety | 15+ | Wrong deletions, missing audit logs, auth bypass | CRITICAL |
| Authorization | 5+ | Cross-team access, privilege escalation | CRITICAL |
| Error recovery | 5+ | Partial commits, zombie records, inconsistent state | HIGH |
| **Total** | **55+** | **Real bugs** | **HIGH** |

---

## What Changed?

### Before
- Testing that functions return their definitions
- Testing that SQL COUNT() works
- Testing that Python operators work
- Testing sequential operations
- Accepting any exception as "validation"
- Happy path only
- **Result**: 260 passing tests, 0 bugs found, 4 bugs found manually

### After
- Testing actual attack vectors
- Testing race conditions with concurrent operations
- Testing destructive operations don't destroy wrong things
- Testing with malicious input
- Strong assertions that explain what's wrong
- Error paths and authorization
- **Result**: Tests that would actually find bugs

---

## Examples of Bugs These Tests Would Find

### 1. Race Condition in Team Join
**Code**:
```python
def join_team(user, team):
    if not team.is_full():  # CHECK
        DiscordLink.objects.create(user=user, team=team)  # CREATE
```

**Bug**: Two users can both pass the check before either creates link.
**Old test**: ✗ Would not find (sequential operations)
**New test**: ✓ Would find (concurrent operations)

### 2. Path Traversal in Filename
**Code**:
```python
TicketAttachment.objects.create(
    filename=uploaded_file.name,  # Not sanitized!
)
```

**Bug**: Filename could be "../../../etc/passwd"
**Old test**: ✗ Not tested (0% coverage)
**New test**: ✓ Would find (tests malicious filenames)

### 3. Admin Account Deactivation
**Code**:
```python
# Deactivate ALL links
links = DiscordLink.objects.filter(is_active=True)  # Missing filter!
for link in links:
    link.is_active = False
```

**Bug**: Deactivates admin accounts too
**Old test**: ✗ Not tested (0% coverage)
**New test**: ✓ Would find (verifies admin links stay active)

### 4. Rate Limit Bypass
**Code**:
```python
def try_action():
    count = RateLimit.objects.filter(...).count()  # CHECK
    if count < 5:
        RateLimit.objects.create(...)  # CREATE
```

**Bug**: Race condition between check and create
**Old test**: ✗ Would not find (tests definition)
**New test**: ✓ Would find (10 concurrent requests)

---

## Metrics That Actually Matter

### Old Metrics (Misleading)
- ✓ 260 passing tests
- ✓ 53% coverage
- ✓ 22 property-based tests
- ✗ 0 bugs found
- ✗ 4 bugs found manually
- ✗ 0% coverage of security-critical code

### New Metrics (Honest)
- Tests that verify security requirements
- Tests that use malicious input
- Tests that run concurrently
- Tests with strong assertions
- Tests of actual attack vectors
- Tests that import 0% coverage modules

---

## Bottom Line

**Old approach**: "We have 260 passing tests!" (but they test tautologies)
**New approach**: "We have 55 tests that test actual attack vectors and race conditions"

**Old result**: 0 bugs found by tests, 4 bugs found manually
**New result**: Tests would find the bugs that manual review found

**Value difference**:
- 260 tautology tests: 0 bugs found
- 4 minutes of code review: 4 bugs found
- 55 attack-vector tests: Would find those 4 bugs + race conditions

**The lesson**: Quality > Quantity. Test attack vectors, not definitions.
