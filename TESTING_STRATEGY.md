# WCComps Bot - State-of-the-Art Testing Strategy

## Executive Summary

This document outlines a comprehensive testing strategy for the WCComps Discord bot and WebUI, designed to detect functionality breaks, bugs, and security vulnerabilities before they reach production. The strategy prioritizes **useful, high-value tests** over raw coverage metrics, focusing on end-to-end functionality validation.

**Current State:**
- 97 unit tests with 59% code coverage
- Strong property-based testing foundation with Hypothesis
- Integration tests with real PostgreSQL, Authentik, Discord APIs
- Critical gaps: 0% coverage in authentik_manager.py, ticketing.py, unified_dashboard.py, competition_timer.py

**Goals:**
- Ensure all WebUI functionality is tested end-to-end
- Ensure all Discord bot commands and workflows are validated
- Detect security vulnerabilities through targeted testing
- Use property-based testing to find edge cases and data corruption bugs
- Focus on functional coverage over line coverage metrics

---

## Testing Principles

### 1. Quality Over Quantity
- **No vanity metrics**: We don't care about 100% line coverage
- **Functional coverage**: Test every user-facing feature end-to-end
- **Useful tests**: Each test must validate real functionality or catch real bugs
- **Bug-driven development**: If a test finds a bug, that's a success (stop and fix)

### 2. State-of-the-Art Techniques
- **Property-based testing** (Hypothesis): Generate edge cases automatically
- **Model-based testing**: Test state machines and complex workflows
- **Security testing**: OWASP Top 10, authentication, authorization
- **Chaos testing**: Simulate failures, race conditions, concurrent operations
- **Browser automation** (Playwright): Real UI testing with JavaScript execution
- **API contract testing**: Verify integrations with Discord, Authentik

### 3. Verification, Not Speculation
- **Check all inferences**: Don't assume functionality works
- **Real data validation**: Use actual test data, not mocks where possible
- **Integration over isolation**: Test with real databases, APIs when practical
- **Defensive testing**: Test error paths, not just happy paths

---

## Current State Analysis

### Test Coverage Overview

| Component | Current Coverage | Test Quality | Gaps |
|-----------|-----------------|--------------|------|
| **Bot Core** | 59% overall | Good | authentik_manager (0%), ticketing cog (0%) |
| **Linking** | 89% | Excellent | Edge cases in OAuth flow |
| **Discord Manager** | 65% | Good | Error handling, cleanup operations |
| **Queue Processing** | 62% | Good | Failure scenarios, backoff edge cases |
| **Ticketing** | 0% | None | Complete gap - no tests exist |
| **Unified Dashboard** | 0% | None | No tests for live updates |
| **Competition Timer** | 0% | None | No tests for lifecycle |
| **WebUI** | Unknown | Partial | Only integration tests exist |

### Existing Test Strengths

1. **Property-Based Testing** (test_property_based.py)
   - Excellent use of Hypothesis for data validation
   - Tests invariants (member count >= 0, rate limits, expiration)
   - Input validation fuzzing (discord IDs, team numbers)
   - Stateful testing (operations sequences)

2. **Integration Tests** (web/integration_tests/)
   - Real PostgreSQL, Authentik, Discord APIs
   - Browser automation with Playwright
   - Critical tests run before deployment
   - Load testing (50-100 concurrent operations)

3. **Async Testing** (pytest-asyncio)
   - Proper async/await patterns
   - Mock Discord interactions
   - Concurrent operation testing

### Critical Gaps

1. **WebUI E2E Coverage**
   - Team ticket dashboard not tested
   - Create ticket form not validated
   - Ops dashboard filters/search not tested
   - School info editing not tested
   - Role mapping UI not tested

2. **Discord Bot Commands**
   - Ticketing cog (0% coverage) - no tests for /ticket command
   - Admin competition commands not tested
   - Help panels not tested
   - Error messages not validated

3. **Security Testing**
   - No CSRF validation tests
   - No SQL injection tests
   - No XSS tests
   - No authorization bypass tests
   - No session fixation tests

4. **Background Services**
   - DiscordQueueProcessor edge cases
   - CompetitionTimer accuracy
   - UnifiedDashboard debouncing
   - Database connection pool exhaustion

---

## Testing Strategy

### Layer 1: Unit Tests (Fast, Isolated)

**Purpose**: Test individual functions and classes in isolation
**Speed**: < 1 second per test
**Database**: SQLite in-memory

**Coverage Goals:**
- All business logic functions
- All model methods
- All utility functions
- All permission checks
- All validation logic

**Tools:**
- pytest + pytest-django
- unittest.mock for external services
- AsyncMock for Discord API calls

### Layer 2: Property-Based Tests (Generative)

**Purpose**: Find edge cases, data corruption, invariant violations
**Speed**: < 10 seconds per test (50-100 examples)
**Database**: SQLite in-memory

**Coverage Goals:**
- All data models (invariants, constraints)
- All state machines (valid transitions)
- All algorithms (round-trip properties)
- All input validation (fuzzing)
- All concurrent operations (race conditions)

**Tools:**
- Hypothesis for test generation
- Custom strategies for domain models
- Stateful testing for workflows

**Advanced Strategies:**
1. **Composite Strategies**: Generate complex, realistic data
2. **Stateful Testing**: Test command sequences (RuleBasedStateMachine)
3. **Shrinking**: Automatically minimize failing examples
4. **Model-Based Testing**: Test against reference implementations

### Layer 3: Integration Tests (Real Services)

**Purpose**: Test interactions with real external services
**Speed**: < 60 seconds for critical, < 5 minutes for comprehensive
**Database**: Real PostgreSQL

**Coverage Goals:**
- OAuth flows (Authentik)
- Discord API operations
- Database transactions
- File uploads/downloads
- API rate limiting

**Tools:**
- pytest with real database
- Real Authentik test account
- Real Discord test guild (Team 50)
- Playwright for browser automation

### Layer 4: End-to-End Tests (Full Workflows)

**Purpose**: Validate complete user journeys
**Speed**: < 2 minutes per workflow
**Database**: Real PostgreSQL

**Coverage Goals:**
- Every user-facing feature (WebUI + Discord)
- Every admin operation
- Every error scenario
- Every permission level

**Tools:**
- Playwright for WebUI testing
- Discord.py test client for bot testing
- Real database and APIs

### Layer 5: Security Tests (Vulnerability Detection)

**Purpose**: Find security vulnerabilities before attackers do
**Speed**: Varies (< 30 seconds for most)
**Database**: Real PostgreSQL or SQLite

**Coverage Goals:**
- OWASP Top 10 vulnerabilities
- Authentication/authorization bypasses
- Input validation failures
- Session security
- CSRF protection
- SQL injection
- XSS vulnerabilities
- Path traversal
- Insecure deserialization

**Tools:**
- pytest for automated tests
- Manual penetration testing scenarios
- OWASP ZAP integration (optional)

### Layer 6: Performance & Load Tests (Stress Testing)

**Purpose**: Ensure system handles production load
**Speed**: < 10 minutes
**Database**: Real PostgreSQL

**Coverage Goals:**
- 50+ concurrent users
- 100+ concurrent requests
- Database connection pool limits
- Memory leak detection
- Query performance under load

**Tools:**
- pytest-xdist for parallel execution
- Custom load generators
- Database query profiling

---

## Detailed Test Plans

### A. WebUI End-to-End Testing

#### A1. Authentication & Authorization

**Test Cases:**
1. **OAuth Login Flow**
   - User clicks "Login with Authentik"
   - Redirected to Authentik
   - Logs in with credentials
   - Redirected back to WebUI
   - Session established correctly
   - User groups loaded from Authentik

2. **Permission Enforcement**
   - Blue team member can only see own tickets
   - Support can see all tickets
   - Admin can perform all operations
   - GoldTeam can edit school info
   - Unauthorized access returns 403

3. **Session Management**
   - Session persists across requests
   - Session expires after timeout
   - CSRF tokens validated on POST requests
   - Secure cookies (HTTPS only in production)

**Property-Based Tests:**
- Generate random user/group combinations
- Verify permissions are always enforced correctly
- Test session token generation randomness

**Security Tests:**
- Session fixation attempts
- CSRF bypass attempts
- Authorization header manipulation
- Cookie theft scenarios

#### A2. Team Ticket Dashboard

**Test Cases:**
1. **Ticket List Display**
   - All team tickets displayed
   - Correct status colors (open/claimed/resolved)
   - Proper sorting (newest first)
   - No tickets from other teams visible
   - Empty state when no tickets

2. **Ticket Filtering**
   - Filter by status (open/claimed/resolved)
   - Filter by category
   - Search by ticket number
   - Search by title/description
   - Combined filters work correctly

3. **Ticket Details**
   - Click ticket to view details
   - All fields displayed correctly
   - Comments visible
   - Attachments downloadable
   - History timeline shown

**Browser Tests:**
- JavaScript loads correctly
- No console errors
- Responsive design works
- Buttons are clickable
- Forms submit properly

#### A3. Create Ticket Form

**Test Cases:**
1. **Form Validation**
   - Category is required
   - Title is required (max 200 chars)
   - Description is required (max 5000 chars)
   - File upload size limits (10MB)
   - MIME type validation
   - Form shows validation errors

2. **Ticket Creation**
   - Valid form submission creates ticket
   - Ticket number generated correctly (T050-001)
   - Discord thread created
   - Dashboard updated
   - User redirected to ticket detail
   - Email notification sent (if enabled)

3. **Error Handling**
   - Network errors shown gracefully
   - Database errors handled
   - Concurrent submissions handled
   - File upload failures handled

**Property-Based Tests:**
- Generate random valid/invalid form data
- Verify validation catches all bad inputs
- Test boundary conditions (max lengths, sizes)

**Security Tests:**
- XSS in title/description
- File upload bypass (PHP, executable files)
- Path traversal in filenames
- CSRF token validation
- SQL injection in search fields

#### A4. Operations Dashboard

**Test Cases:**
1. **Ticket Management**
   - View all tickets from all teams
   - Claim ticket assigns to current user
   - Resolve ticket with points charged
   - Cancel ticket with reason
   - Reopen resolved ticket
   - Bulk operations work correctly

2. **Filtering & Search**
   - Filter by team
   - Filter by status
   - Filter by category
   - Filter by assigned user
   - Search by ticket number/title
   - Combined filters

3. **Live Updates**
   - New tickets appear automatically
   - Status changes update dashboard
   - Claimed tickets show assignee
   - Stale ticket warnings appear

**Browser Tests:**
- Dashboard loads < 3 seconds
- Filters update without page reload
- Bulk selection checkboxes work
- Pagination works correctly

#### A5. School Info Management

**Test Cases:**
1. **View School Info** (GoldTeam only)
   - List all teams
   - Show school name, IP ranges
   - Show contact information
   - Pagination works

2. **Edit School Info** (GoldTeam only)
   - Edit form loads with current data
   - Validation works (required fields)
   - Save updates database
   - Audit log created
   - Non-GoldTeam users cannot access

**Security Tests:**
- Authorization bypass attempts
- SQL injection in school name
- XSS in contact fields
- CSRF validation

#### A6. Group Role Mappings

**Test Cases:**
1. **View Mappings** (GoldTeam only)
   - List all Authentik group → Discord role mappings
   - Show current configuration
   - Multiple guilds supported

2. **Edit Mappings** (GoldTeam only)
   - Add new mapping
   - Remove mapping
   - Validate Discord role IDs
   - Changes apply to bot

**Security Tests:**
- Only GoldTeam can access
- Validate role IDs are numeric
- Prevent mapping to system roles

### B. Discord Bot Testing

#### B1. User Commands

**Test Cases:**

##### /link Command
1. **Happy Path**
   - User runs /link
   - Receives OAuth URL
   - URL includes unique token
   - Token expires in 15 minutes
   - Rate limit not exceeded

2. **Error Cases**
   - User already linked → error message
   - Rate limit exceeded (5/hour) → error message
   - Database error → graceful error
   - Token generation fails → error

3. **OAuth Flow** (Integration)
   - Click link → redirects to Authentik
   - Login with credentials
   - Redirected back to web
   - Discord roles assigned
   - Team assignment correct
   - Success page shown

**Property-Based Tests:**
- Generate random Discord IDs
- Verify token uniqueness
- Test expiration edge cases

##### /team-info Command
1. **Display Team Info**
   - Shows team number
   - Shows member count / max members
   - Shows member list
   - Shows team is full/not full

2. **Error Cases**
   - User not linked → error
   - User not on team → error
   - Database error → graceful error

##### /ticket Command
1. **Create Ticket**
   - Category dropdown works
   - Description required
   - Ticket number generated
   - Thread created in team category
   - Dashboard updated
   - Confirmation message shown

2. **Error Cases**
   - User not linked → error
   - Invalid category → error
   - Description too long → error
   - Database error → graceful error

**Security Tests:**
- XSS in ticket description
- SQL injection in category
- Rate limiting enforced

#### B2. Admin Commands

##### /teams Commands
1. **/teams list**
   - Shows all 50 teams
   - Shows member counts
   - Pagination works
   - Only admins can run

2. **/teams info <team_number>**
   - Shows detailed team info
   - Shows all members
   - Shows Discord role/category IDs
   - Validates team number (1-50)

3. **/teams unlink <user>**
   - Unlinks Discord user
   - Removes from team
   - Removes Discord roles
   - Audit log created

4. **/teams remove <team> <user>**
   - Removes user from team
   - Keeps Authentik link
   - Updates member count
   - Audit log created

5. **/teams reset <team>**
   - Confirms before reset
   - Removes all members
   - Resets team counter
   - Clears Discord roles
   - Audit log created

**Property-Based Tests:**
- Random team numbers (validate 1-50 range)
- Random member counts
- Test removal sequences

**Security Tests:**
- Only admins can run commands
- Team number validation
- Audit logging for all actions

##### /tickets Commands (Admin)
1. **/tickets create <team> <category> <description>**
   - Admin can create tickets for any team
   - Ticket number generated correctly
   - Thread created
   - Dashboard updated

2. **/tickets cancel <ticket_number>**
   - Admin can cancel any ticket
   - Reason required
   - Thread archived
   - Audit log created

3. **/tickets reopen <ticket_number>**
   - Admin can reopen resolved tickets
   - Status changed to open
   - Thread unarchived
   - Dashboard updated

**Security Tests:**
- Only admins can run
- Ticket number validation
- Audit all operations

##### /competition Commands
1. **/competition start**
   - Starts competition
   - Enables applications in Authentik
   - Sends announcement
   - Updates competition config

2. **/competition end**
   - Ends competition
   - Disables applications
   - Archives all tickets
   - Generates report

3. **/competition set-start-time <datetime>**
   - Sets start time
   - Validates future date
   - Updates config

4. **/competition set-max-members <count>**
   - Sets max team members
   - Validates positive number
   - Updates all teams

5. **/competition toggle-blueteams**
   - Enables/disables team applications
   - Updates Authentik

6. **/competition set-apps <app1,app2>**
   - Sets controlled applications
   - Validates app slugs exist in Authentik

7. **/competition broadcast <message>**
   - Sends message to all teams
   - Confirms before sending
   - Audit log created

**Security Tests:**
- Only admins can run
- Validate all inputs
- Test Authentik API errors
- Audit all operations

##### /admin sync-roles
1. **Multi-Guild Sync**
   - Syncs roles across all guilds
   - Handles BlackTeam, WhiteTeam, OrangeTeam, RedTeam
   - Handles missing users gracefully
   - Audit log for all changes

**Security Tests:**
- Only admins can run
- Validate guild IDs
- Handle API errors

#### B3. Background Services

##### DiscordQueueProcessor
1. **Task Processing**
   - Processes pending tasks
   - Respects rate limits
   - Exponential backoff on failure
   - Max retries enforced (5)
   - Failed tasks logged

2. **Task Types**
   - create_thread: Creates Discord thread
   - update_embed: Updates message embed
   - archive_thread: Archives thread after 60s
   - assign_role: Assigns role to user
   - remove_role: Removes role from user
   - send_message: Sends message to channel

**Property-Based Tests:**
- Generate random task sequences
- Verify processing order
- Test retry logic with failures
- Test rate limit handling

**Error Cases:**
- Discord API errors (403, 404, 429, 500)
- Network timeouts
- Invalid task parameters
- Database connection loss

##### CompetitionTimer
1. **Application Control**
   - Polls every 1 minute
   - Enables apps at start_time
   - Disables apps at end_time
   - Handles clock drift
   - Handles Authentik API errors

**Property-Based Tests:**
- Random start/end times
- Test edge cases (exactly at boundary)
- Test timezone handling

**Error Cases:**
- Authentik API down
- Network errors
- Invalid application slugs
- Clock skew

##### UnifiedDashboard
1. **Dashboard Updates**
   - Updates on ticket status change
   - Debounces rapid updates (5 seconds)
   - Color codes tickets (red/orange/green)
   - Shows stale warnings (30m, 1h, 2h)
   - Interactive buttons (claim/resolve)

**Property-Based Tests:**
- Generate random ticket events
- Verify debouncing works
- Test concurrent updates

**Error Cases:**
- Discord API errors
- Message not found (deleted)
- Channel not found
- Permission errors

#### B4. Permission System

**Test Cases:**
1. **Permission Cache**
   - Cache hit returns cached value
   - Cache miss queries database
   - Cache expires after 5 minutes
   - Cache invalidates on link change

2. **Permission Checks**
   - `is_admin_async()`: Checks WCComps_Discord_Admin
   - `can_manage_tickets_async()`: Checks WCComps_Ticketing_Admin
   - `can_support_tickets_async()`: Checks WCComps_Ticketing_Support
   - `is_gold_team_async()`: Checks WCComps_GoldTeam
   - `get_team_number()`: Extracts from WCComps_BlueTeam01-50

**Property-Based Tests:**
- Generate random group combinations
- Verify permission logic is correct
- Test cache behavior

**Security Tests:**
- Permission bypass attempts
- Group name spoofing
- Cache poisoning
- Race conditions in permission checks

### C. Security Testing

#### C1. Authentication Vulnerabilities

**Test Cases:**
1. **Session Management**
   - Session fixation attack
   - Session hijacking via XSS
   - Session timeout enforcement
   - Concurrent session handling
   - Session token randomness (property-based)

2. **OAuth Flow**
   - State parameter validation (CSRF)
   - Redirect URI validation
   - Token replay attacks
   - Authorization code reuse
   - Scope verification

3. **Password Security** (Authentik integration)
   - Generated passwords meet complexity
   - Passwords never logged
   - Passwords encrypted in transit (HTTPS)
   - Password reset requires verification

**Automated Tests:**
- Property-based token generation (test randomness)
- CSRF token validation on all POST requests
- Secure cookie flags (Secure, HttpOnly, SameSite)

#### C2. Authorization Vulnerabilities

**Test Cases:**
1. **Horizontal Privilege Escalation**
   - Team member accessing other team's tickets
   - User viewing other user's data
   - Team member performing admin actions

2. **Vertical Privilege Escalation**
   - Non-admin running admin commands
   - Non-support claiming tickets
   - Non-GoldTeam editing school info

3. **Insecure Direct Object References (IDOR)**
   - Accessing ticket by ID without permission
   - Editing team by number without permission
   - Viewing Discord link data of other users

**Automated Tests:**
- Test all endpoints with different permission levels
- Verify 403 responses for unauthorized access
- Test ticket access with different team memberships

#### C3. Input Validation & Injection

**Test Cases:**
1. **SQL Injection**
   - Ticket search fields
   - Team name filters
   - User search
   - File attachment metadata

2. **XSS (Cross-Site Scripting)**
   - Ticket titles and descriptions
   - Comments in tickets
   - School info fields
   - Usernames in display

3. **Command Injection**
   - File upload filenames
   - Discord message content
   - Authentik API parameters

4. **Path Traversal**
   - File attachment downloads
   - Static file serving
   - Template inclusion

**Property-Based Tests:**
- Generate payloads from OWASP lists
- Test all input fields systematically
- Verify escaping/sanitization

**Automated Tests:**
```python
@pytest.mark.security
class TestSQLInjection:
    @given(payload=st.sampled_from(SQL_INJECTION_PAYLOADS))
    def test_ticket_search_sql_injection(self, client, payload):
        response = client.get(f"/ops/tickets/?search={payload}")
        # Should not execute SQL, should escape or return error
        assert response.status_code in [200, 400]
        # Check that payload was escaped
        assert "'; DROP TABLE" not in response.content.decode()
```

#### C4. CSRF Protection

**Test Cases:**
1. **CSRF Token Validation**
   - All POST requests require CSRF token
   - Token is unique per session
   - Token is not predictable
   - Missing token returns 403
   - Invalid token returns 403

2. **CSRF Bypass Attempts**
   - GET request with side effects
   - JSON API without CSRF
   - Referer header spoofing
   - Origin header manipulation

**Automated Tests:**
- Submit forms without CSRF token → 403
- Submit forms with wrong CSRF token → 403
- Test all state-changing operations

#### C5. File Upload Vulnerabilities

**Test Cases:**
1. **File Type Validation**
   - Executable files rejected (.exe, .sh, .php)
   - MIME type verification (not just extension)
   - Magic byte checking
   - Double extension attacks (.jpg.php)

2. **File Size Limits**
   - 10MB max size enforced
   - Zip bomb detection
   - Memory exhaustion protection

3. **File Storage Security**
   - Files stored outside web root
   - Filenames sanitized (no path traversal)
   - Files served with correct Content-Type
   - Download-only (no execution)

**Property-Based Tests:**
- Generate random file extensions
- Generate random MIME types
- Test boundary sizes

**Automated Tests:**
```python
@pytest.mark.security
class TestFileUpload:
    def test_php_file_rejected(self, client):
        file = SimpleUploadedFile("shell.php", b"<?php system($_GET['cmd']); ?>")
        response = client.post("/create-ticket/", {
            "category": "other",
            "title": "Test",
            "description": "Test",
            "attachment": file,
        })
        assert response.status_code == 400  # Rejected

    def test_double_extension_rejected(self, client):
        file = SimpleUploadedFile("image.jpg.php", b"malicious")
        # Should be rejected
```

#### C6. Rate Limiting

**Test Cases:**
1. **Link Rate Limiting**
   - 5 attempts per hour enforced
   - Counter resets after 1 hour
   - Attempt logging works

2. **Comment Rate Limiting**
   - 5 comments per minute per ticket
   - 10 comments per minute per user
   - Rate limit messages shown

3. **API Rate Limiting**
   - Discord API rate limits respected
   - Authentik API rate limits respected
   - Exponential backoff on 429 responses

**Property-Based Tests:**
- Generate random request patterns
- Verify rate limits always enforced
- Test edge cases (exactly at limit)

#### C7. Secure Configuration

**Test Cases:**
1. **Production Settings** (when DEBUG=False)
   - ALLOWED_HOSTS configured
   - SECURE_SSL_REDIRECT enabled (if using HTTPS)
   - SESSION_COOKIE_SECURE = True
   - CSRF_COOKIE_SECURE = True
   - SECURE_HSTS_SECONDS = 31536000
   - X_FRAME_OPTIONS = 'DENY'
   - SECURE_CONTENT_TYPE_NOSNIFF = True
   - SECURE_BROWSER_XSS_FILTER = True

2. **Secret Management**
   - No secrets in code
   - All secrets in environment variables
   - SECRET_KEY is random (50+ chars)
   - Database password is strong
   - API tokens not logged

**Automated Tests:**
- Verify settings in production mode
- Test HSTS headers present
- Test secure cookie flags

### D. Property-Based Testing (Hypothesis)

#### D1. Model Invariants

**Existing Tests** (test_property_based.py):
- Team.is_full() iff member_count >= max_members ✓
- Team.get_member_count() >= 0 always ✓
- Only one active DiscordLink per discord_id ✓
- Token.is_expired() iff now > expires_at ✓
- Rate limits enforce correctly ✓

**Additional Tests Needed:**

1. **Ticket Number Uniqueness**
```python
@given(
    team_number=st.integers(min_value=1, max_value=50),
    ticket_count=st.integers(min_value=1, max_value=100)
)
def test_ticket_numbers_unique_per_team(team_number, ticket_count):
    """Property: Ticket numbers are unique within a team."""
    team = create_team(team_number)
    ticket_numbers = []
    for _ in range(ticket_count):
        ticket = create_ticket(team)
        ticket_numbers.append(ticket.ticket_number)

    # Property: All ticket numbers unique
    assert len(ticket_numbers) == len(set(ticket_numbers))
    # Property: All follow format T{team:03d}-{counter:03d}
    for tn in ticket_numbers:
        assert tn.startswith(f"T{team_number:03d}-")
```

2. **Ticket Status Transitions**
```python
@given(transitions=st.lists(
    st.sampled_from(['claim', 'resolve', 'cancel', 'reopen']),
    min_size=1, max_size=20
))
def test_ticket_status_transitions(transitions):
    """Property: Ticket status transitions are valid."""
    ticket = create_ticket()
    assert ticket.status == 'open'

    for transition in transitions:
        old_status = ticket.status
        try:
            if transition == 'claim' and ticket.status == 'open':
                ticket.claim(user_id)
                assert ticket.status == 'claimed'
            elif transition == 'resolve' and ticket.status == 'claimed':
                ticket.resolve(user_id, points=10)
                assert ticket.status == 'resolved'
            elif transition == 'cancel' and ticket.status in ['open', 'claimed']:
                ticket.cancel(user_id)
                assert ticket.status == 'cancelled'
            elif transition == 'reopen' and ticket.status == 'resolved':
                ticket.reopen(user_id)
                assert ticket.status == 'open'
            else:
                # Invalid transition should raise error or be no-op
                pass
        except ValueError:
            # Invalid transitions may raise errors - that's OK
            pass
```

3. **Discord ID Validation**
```python
@given(discord_id=st.integers(min_value=-1000000, max_value=1000000000000000000000))
def test_discord_id_validation(discord_id):
    """Property: Invalid Discord IDs are rejected."""
    # Valid Discord IDs are 17-19 digit positive integers
    try:
        link = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username="test",
            authentik_username="test",
            authentik_user_id="test"
        )
        # If it succeeded, verify it's valid
        assert discord_id > 0
        assert discord_id >= 100000000000000000  # 17 digits minimum
    except (ValueError, ValidationError, IntegrityError):
        # Invalid IDs should be rejected
        pass
```

4. **Team Member Limits**
```python
@given(
    max_members=st.integers(min_value=1, max_value=20),
    add_attempts=st.integers(min_value=0, max_value=30)
)
def test_team_cannot_exceed_max_members(max_members, add_attempts):
    """Property: Team member count never exceeds max_members."""
    team = create_team(max_members=max_members)

    added = 0
    for i in range(add_attempts):
        if not team.is_full():
            create_link(team=team, discord_id=base_id + i)
            added += 1

    # Property: Added exactly max_members (or fewer if attempts < max)
    assert added == min(max_members, add_attempts)
    assert team.get_member_count() == added
    assert team.get_member_count() <= max_members
```

#### D2. Stateful Testing

**Test Complex Workflows with State Machines:**

```python
from hypothesis.stateful import RuleBasedStateMachine, rule, precondition

class TicketLifecycle(RuleBasedStateMachine):
    """Stateful test for ticket lifecycle."""

    def __init__(self):
        super().__init__()
        self.ticket = None
        self.status = 'open'

    @rule()
    def create_ticket(self):
        """Create a new ticket."""
        if self.ticket is None:
            self.ticket = Ticket.objects.create(...)
            self.status = 'open'

    @rule()
    @precondition(lambda self: self.status == 'open')
    def claim_ticket(self):
        """Claim the ticket."""
        self.ticket.claim(user_id)
        self.status = 'claimed'

    @rule()
    @precondition(lambda self: self.status == 'claimed')
    def resolve_ticket(self):
        """Resolve the ticket."""
        self.ticket.resolve(user_id, points=10)
        self.status = 'resolved'

    @rule()
    @precondition(lambda self: self.status in ['open', 'claimed'])
    def cancel_ticket(self):
        """Cancel the ticket."""
        self.ticket.cancel(user_id)
        self.status = 'cancelled'

    @rule()
    @precondition(lambda self: self.status == 'resolved')
    def reopen_ticket(self):
        """Reopen the ticket."""
        self.ticket.reopen(user_id)
        self.status = 'open'

    def teardown(self):
        """Verify invariants after each sequence."""
        if self.ticket:
            # Property: Database status matches our tracking
            self.ticket.refresh_from_db()
            assert self.ticket.status == self.status

TestTicketWorkflow = TicketLifecycle.TestCase
```

#### D3. Round-Trip Properties

**Test that encode/decode operations are inverses:**

```python
@given(ticket_data=st.fixed_dictionaries({
    'team_number': st.integers(min_value=1, max_value=50),
    'category': st.sampled_from(['technical', 'scoring', 'other']),
    'title': st.text(min_size=1, max_size=200),
    'description': st.text(min_size=1, max_size=5000),
}))
def test_ticket_serialization_round_trip(ticket_data):
    """Property: Ticket serialization/deserialization is lossless."""
    # Create ticket from data
    ticket = create_ticket(**ticket_data)

    # Serialize to dict
    serialized = ticket.to_dict()

    # Deserialize back
    deserialized = Ticket.from_dict(serialized)

    # Property: Round trip preserves data
    assert deserialized.team_number == ticket.team_number
    assert deserialized.category == ticket.category
    assert deserialized.title == ticket.title
    assert deserialized.description == ticket.description
```

#### D4. Chaos/Fuzz Testing

**Test resilience to unexpected inputs:**

```python
@given(payload=st.text(min_size=0, max_size=10000))
def test_ticket_description_handles_any_text(payload):
    """Property: Any text input is handled safely (no crashes)."""
    try:
        ticket = create_ticket(description=payload)
        # Should either succeed or raise ValidationError
        assert ticket.description == payload
    except ValidationError as e:
        # Validation errors are acceptable
        assert 'description' in str(e)
    except Exception as e:
        # Should never crash with unexpected errors
        pytest.fail(f"Unexpected exception: {e}")

@given(
    discord_id=st.integers(),
    username=st.text(),
    authentik_username=st.text(),
    authentik_user_id=st.text(),
)
def test_discord_link_handles_any_input(discord_id, username, authentik_username, authentik_user_id):
    """Property: DiscordLink handles any input safely."""
    try:
        link = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username=username,
            authentik_username=authentik_username,
            authentik_user_id=authentik_user_id,
        )
        # If it succeeded, verify constraints
        assert link.discord_id > 0
        assert len(link.discord_username) > 0
    except (ValueError, ValidationError, IntegrityError):
        # Validation/integrity errors are acceptable
        pass
    except Exception as e:
        # Should not crash with unexpected errors
        pytest.fail(f"Unexpected exception: {e}")
```

### E. Performance & Load Testing

#### E1. Database Query Performance

**Test Cases:**
1. **N+1 Query Detection**
   - List all tickets: < 10 queries regardless of count
   - Ticket detail: < 5 queries
   - Dashboard: < 15 queries
   - Use `select_related()` and `prefetch_related()`

2. **Query Optimization**
   - Index usage verified
   - Explain plans reviewed
   - Slow query log monitored

**Automated Tests:**
```python
def test_ticket_list_queries(django_assert_num_queries):
    # Create 100 tickets
    create_tickets(count=100)

    # Should use < 10 queries regardless of count
    with django_assert_num_queries(10):
        response = client.get("/ops/tickets/")
        assert len(response.context['tickets']) == 100
```

#### E2. Concurrent Operations

**Test Cases:**
1. **Concurrent Ticket Claims**
   - 10 users try to claim same ticket
   - Only 1 succeeds
   - Others get error message
   - No race condition

2. **Concurrent Link Creation**
   - Same discord_id links 5 times concurrently
   - Only 1 active link created
   - Unique constraint enforced

3. **Concurrent Ticket Creation**
   - Same team creates 10 tickets concurrently
   - All get unique ticket numbers
   - No duplicate counters

**Property-Based Tests:**
```python
@given(concurrent_operations=st.integers(min_value=2, max_value=20))
def test_concurrent_ticket_claims(concurrent_operations):
    """Property: Only one concurrent claim succeeds."""
    ticket = create_ticket()

    # Simulate concurrent claims
    with ThreadPoolExecutor(max_workers=concurrent_operations) as executor:
        futures = [
            executor.submit(claim_ticket, ticket.id, user_id=i)
            for i in range(concurrent_operations)
        ]
        results = [f.result() for f in futures]

    # Property: Exactly one claim succeeded
    successes = [r for r in results if r['success']]
    assert len(successes) == 1
```

#### E3. Load Testing

**Test Cases:**
1. **50 Concurrent Users**
   - 50 users browse tickets simultaneously
   - All responses < 2 seconds
   - No database connection exhaustion
   - No memory leaks

2. **100 Concurrent Requests**
   - 100 requests to dashboard
   - Server remains responsive
   - Connection pool handles load
   - Gunicorn workers don't crash

3. **Sustained Load**
   - 10 requests/second for 5 minutes
   - Response times stable
   - Memory usage stable
   - No connection leaks

**Automated Tests:**
```python
@pytest.mark.load
def test_sustained_dashboard_load():
    """Load test: 10 req/sec for 5 minutes."""
    duration = 300  # 5 minutes
    rate = 10  # req/sec

    start = time.time()
    request_count = 0
    errors = 0
    response_times = []

    while time.time() - start < duration:
        t0 = time.time()
        try:
            response = client.get("/ops/tickets/")
            assert response.status_code == 200
            response_times.append(time.time() - t0)
        except Exception:
            errors += 1

        request_count += 1

        # Rate limiting
        elapsed = time.time() - start
        expected = int(elapsed * rate)
        if request_count >= expected:
            time.sleep(1/rate)

    # Verify performance
    assert errors < request_count * 0.01  # < 1% errors
    assert np.percentile(response_times, 95) < 2.0  # p95 < 2s
    assert np.percentile(response_times, 99) < 5.0  # p99 < 5s
```

#### E4. Connection Pool Testing

**Test Cases:**
1. **Connection Pool Exhaustion**
   - 50 connections (DB max is 50)
   - All return to pool after use
   - No connection leaks
   - Timeout errors handled gracefully

2. **Connection Reuse**
   - Connections are reused
   - CONN_MAX_AGE respected (600s)
   - Stale connections closed

**Automated Tests:**
```python
@pytest.mark.load
def test_connection_pool_exhaustion():
    """Test that connection pool handles exhaustion gracefully."""
    from django.db import connections

    # Get 50 connections (the max)
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [
            executor.submit(lambda: list(Ticket.objects.all()))
            for _ in range(50)
        ]
        results = [f.result() for f in futures]

    # All should succeed (no connection exhaustion)
    assert len(results) == 50

    # Connections should be returned to pool
    # (test by making another query)
    assert Ticket.objects.count() >= 0
```

---

## Test Implementation Plan

### Phase 1: Critical Gaps (Priority 1)

**Goal**: Achieve functional coverage of untested components

1. **Ticketing Cog Tests** (bot/tests/test_ticketing_cog.py)
   - Worker: Test /ticket command
   - Test cases: valid ticket creation, error handling, rate limiting
   - Estimated: 15 tests, 2 hours

2. **Authentik Manager Tests** (bot/tests/test_authentik_manager.py)
   - Worker: Test Authentik API wrapper
   - Test cases: password generation, user management, error handling
   - Estimated: 20 tests, 3 hours

3. **Unified Dashboard Tests** (bot/tests/test_unified_dashboard.py)
   - Worker: Test dashboard updates
   - Test cases: ticket formatting, debouncing, interactive buttons
   - Estimated: 12 tests, 2 hours

4. **Competition Timer Tests** (bot/tests/test_competition_timer.py)
   - Worker: Test application enable/disable
   - Test cases: timing accuracy, error handling
   - Estimated: 10 tests, 1.5 hours

### Phase 2: WebUI E2E Tests (Priority 1)

**Goal**: Test all user-facing WebUI features

5. **Team Ticket Dashboard Tests** (web/integration_tests/test_team_dashboard.py)
   - Worker: Browser-based E2E tests
   - Test cases: list, filter, detail, create ticket
   - Estimated: 15 tests, 3 hours

6. **Ops Dashboard Tests** (web/integration_tests/test_ops_dashboard.py)
   - Worker: Browser-based E2E tests
   - Test cases: claim, resolve, filters, search, bulk ops
   - Estimated: 20 tests, 4 hours

7. **School Info Tests** (web/integration_tests/test_school_info.py)
   - Worker: Browser-based E2E tests
   - Test cases: list, edit, permissions
   - Estimated: 8 tests, 1.5 hours

8. **Group Role Mapping Tests** (web/integration_tests/test_group_role_mappings.py)
   - Worker: Browser-based E2E tests
   - Test cases: view, edit, permissions
   - Estimated: 6 tests, 1 hour

### Phase 3: Security Tests (Priority 1)

**Goal**: Detect common vulnerabilities

9. **Authentication Security Tests** (bot/tests/test_security_auth.py)
   - Worker: Test session, OAuth, CSRF
   - Test cases: session fixation, OAuth attacks, CSRF bypass
   - Estimated: 15 tests, 3 hours

10. **Authorization Security Tests** (bot/tests/test_security_authz.py)
    - Worker: Test permission enforcement
    - Test cases: horizontal/vertical escalation, IDOR
    - Estimated: 20 tests, 3 hours

11. **Input Validation Security Tests** (bot/tests/test_security_injection.py)
    - Worker: Test XSS, SQL injection, command injection
    - Test cases: all input fields, property-based fuzzing
    - Estimated: 25 tests, 4 hours

12. **File Upload Security Tests** (bot/tests/test_security_files.py)
    - Worker: Test file upload validation
    - Test cases: malicious files, path traversal, size limits
    - Estimated: 12 tests, 2 hours

### Phase 4: Property-Based Tests (Priority 2)

**Goal**: Find edge cases and data corruption bugs

13. **Extended Model Properties** (bot/tests/test_property_models.py)
    - Worker: Hypothesis tests for all models
    - Test cases: ticket numbers, status transitions, counters
    - Estimated: 15 tests, 2 hours

14. **Stateful Workflow Tests** (bot/tests/test_property_stateful.py)
    - Worker: Hypothesis stateful testing
    - Test cases: ticket lifecycle, team operations
    - Estimated: 8 tests, 3 hours

15. **Chaos/Fuzz Tests** (bot/tests/test_property_fuzz.py)
    - Worker: Hypothesis fuzzing
    - Test cases: any input to all fields
    - Estimated: 10 tests, 2 hours

### Phase 5: Performance Tests (Priority 2)

**Goal**: Ensure production readiness

16. **Query Performance Tests** (bot/tests/test_performance_queries.py)
    - Worker: Test database query efficiency
    - Test cases: N+1 detection, query counts
    - Estimated: 10 tests, 2 hours

17. **Concurrency Tests** (bot/tests/test_performance_concurrency.py)
    - Worker: Test concurrent operations
    - Test cases: race conditions, locking
    - Estimated: 12 tests, 3 hours

18. **Load Tests** (web/integration_tests/test_load_extended.py)
    - Worker: Sustained load testing
    - Test cases: 50 users, 100 requests, 5 min sustained
    - Estimated: 8 tests, 2 hours

### Phase 6: Discord Bot Commands (Priority 2)

**Goal**: Full coverage of all Discord commands

19. **Admin Team Commands Tests** (bot/tests/test_admin_teams_extended.py)
    - Worker: Test /teams commands
    - Test cases: list, info, unlink, remove, reset
    - Estimated: 15 tests, 2 hours

20. **Admin Ticket Commands Tests** (bot/tests/test_admin_tickets_extended.py)
    - Worker: Test /tickets commands
    - Test cases: create, cancel, reopen
    - Estimated: 12 tests, 2 hours

21. **Admin Competition Commands Tests** (bot/tests/test_admin_competition.py)
    - Worker: Test /competition commands
    - Test cases: start, end, timing, apps, broadcast
    - Estimated: 18 tests, 3 hours

22. **Help Command Tests** (bot/tests/test_help_panels.py)
    - Worker: Test /help command
    - Test cases: help text display, formatting
    - Estimated: 5 tests, 1 hour

---

## Test Execution Strategy

### Test Organization by Speed

**Fast Tests** (< 1s each):
- Unit tests with SQLite
- Mocked external services
- Total: ~200 tests, < 30 seconds

**Medium Tests** (1-10s each):
- Property-based tests (50 examples)
- Database integration tests
- Total: ~50 tests, < 5 minutes

**Slow Tests** (10-60s each):
- Browser automation
- Real API calls
- Total: ~40 tests, < 20 minutes

**Load Tests** (1-10 min each):
- Sustained load tests
- Connection pool tests
- Total: ~10 tests, < 30 minutes

### CI/CD Integration

**Pre-commit** (local):
```bash
pytest -m "not slow" --maxfail=1
```

**PR Validation** (GitHub Actions):
```bash
pytest -m "critical" --cov=bot --cov=web/core --cov=web/team --cov=web/ticketing
```

**Pre-deployment** (deploy.sh):
```bash
pytest -m "critical or integration" --maxfail=1
```

**Nightly** (cron):
```bash
pytest --cov=. --cov-report=html
pytest -m "load"
```

### Parallel Execution

```bash
# Run fast tests in parallel (8 workers)
pytest -n 8 -m "not slow"

# Run slow tests sequentially
pytest -m "slow"
```

---

## Success Criteria

### Functional Coverage Goals

| Component | Target |
|-----------|--------|
| **WebUI Features** | 100% of user-facing features tested E2E |
| **Discord Commands** | 100% of commands tested |
| **Security** | All OWASP Top 10 tested |
| **Critical Paths** | 100% tested (auth, ticketing, linking) |

### Quality Metrics

| Metric | Target |
|--------|--------|
| **Test Count** | 250-300 useful tests |
| **Code Coverage** | 75-85% (not 100%) |
| **Test Speed** | Critical tests < 60s |
| **Test Reliability** | < 1% flaky tests |
| **Bug Detection** | Tests find bugs before production |

### Bug Reporting

**When a test finds a bug:**
1. **STOP** - Do not continue test implementation
2. **Document** the bug (file issue, add comment)
3. **Fix** the bug (or mark as known issue)
4. **Verify** fix with test
5. **Continue** test implementation

**This is a success!** Finding bugs means tests are working.

---

## Test Maintenance

### Keeping Tests Valuable

1. **Delete useless tests**: If a test never fails, consider removing it
2. **Update tests with features**: When code changes, update tests
3. **Refactor duplicated test code**: Use fixtures and helpers
4. **Monitor test performance**: Remove slow tests that don't add value
5. **Review coverage reports**: Focus on untested critical paths

### Test Code Quality

- Test code should be as clean as production code
- Use descriptive test names
- Follow AAA pattern (Arrange, Act, Assert)
- One assertion per test (when practical)
- Use fixtures for common setup

### Documentation

- Every test file has a docstring explaining purpose
- Complex tests have inline comments
- README files in test directories
- Examples of how to run tests

---

## Tools & Technologies

### Testing Frameworks
- **pytest**: Primary test framework
- **pytest-django**: Django integration
- **pytest-asyncio**: Async test support
- **pytest-xdist**: Parallel execution
- **Hypothesis**: Property-based testing

### Browser Automation
- **Playwright**: Modern browser automation
- **Chromium**: Headless browser

### Database
- **PostgreSQL 16**: Production database
- **SQLite**: Fast unit tests

### Code Quality
- **pytest-cov**: Coverage measurement
- **ruff**: Linting
- **mypy**: Type checking
- **bandit**: Security linting (via ruff)

### External Services
- **Authentik**: Real OAuth testing
- **Discord API**: Real bot testing

---

## Risk Mitigation

### Test Environment Isolation

- Test database separate from production (port 5433)
- Test Discord guild separate (Team 50 designated)
- Test Authentik users separate from real users
- Cleanup after each test

### Handling Test Failures

1. **Flaky Tests**
   - Investigate and fix root cause
   - Add retries only as last resort
   - Mark as `@pytest.mark.flaky` if truly non-deterministic

2. **Slow Tests**
   - Optimize or remove
   - Move to load test suite
   - Run less frequently

3. **Breaking Changes**
   - Update tests when intentional
   - Use tests to prevent unintentional breaks

### Security of Test Data

- Never use production credentials in tests
- Test users have minimal permissions
- Test data cleaned up automatically
- No sensitive data in test code

---

## Conclusion

This testing strategy provides comprehensive coverage of the WCComps bot and WebUI through multiple complementary approaches:

1. **Unit tests** for fast feedback on code changes
2. **Property-based tests** to find edge cases automatically
3. **Integration tests** with real services for confidence
4. **E2E tests** to validate complete user workflows
5. **Security tests** to prevent vulnerabilities
6. **Performance tests** to ensure production readiness

The strategy prioritizes **useful tests over coverage metrics**, ensuring that every test adds real value. By focusing on end-to-end functional coverage and using modern testing techniques like property-based testing and browser automation, we can catch bugs before they reach users while maintaining fast, reliable test execution.

**Next Steps**: Implement test workers for each discrete test category, stopping if bugs are found to fix them immediately.
