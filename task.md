# Test Coverage Improvement Plan

Current coverage: 60%

## High Priority

### views.py (26% coverage - 728 lines missing)

#### OAuth/Discord Linking (lines 63-402)
- `discord_link_initiate`: Requires valid token, creates session state, redirects to Discord
- `discord_link_callback`: Handles Discord OAuth response, links account, handles errors
- `oauth_callback`: Handles Authentik OAuth, creates/updates user session
- Test invalid tokens, expired tokens, CSRF protection, duplicate linking attempts

#### Ticket Operations (lines 419-770)
- `team_ticket_detail`: Team can only view own tickets, shows correct status/history
- `team_ticket_list`: Pagination, filtering by status, team isolation
- `ticket_claim`: Only ops can claim, can't claim already-claimed, updates assignee
- `ticket_unclaim`: Only assigned user can unclaim, reverts status
- `ticket_resolve`: Requires claim first, sets points, creates history
- `ticket_cancel`: Permission check, updates status, audit trail
- `ticket_reopen`: Permission check, clears resolution data

#### Ops Ticket Views (lines 787-926)
- `ops_ticket_detail`: Shows full ticket info, comments, attachments
- `ops_add_comment`: Creates comment, links to correct ticket
- `ops_attachment_upload/download`: Already partially tested, verify edge cases

#### Scoring Views (lines 1035-1703)
- `leaderboard`: Calculates scores correctly, respects permissions
- `incident_list`: Shows team's incidents only
- `incident_submit`: Validates input, creates incident, notifies
- `inject_list`: Shows injects for correct team role
- `inject_grade`: Permission check, saves grade, calculates points
- `inject_detail`: Shows inject content, submission status

#### Red/Orange Team Portals (lines 1783-2009)
- `red_team_portal`: Permission check (red team + gold + admin only)
- `red_team_submit_deduction`: Creates deduction, validates points
- `orange_team_portal`: Permission check (orange + gold + admin only)
- `orange_team_submit_inject`: Creates inject submission

#### Export Views (lines 2026-2354)
- `export_tickets_csv`: Correct CSV format, all fields included
- `export_scores_csv`: Calculates totals correctly
- `group_role_mappings`: Shows all teams, member counts, Discord roles

### auth_utils.py (46% coverage)

#### Permission Decorators (lines 88-98, 160-205)
- `require_ops_permission`: Blocks non-ops users, allows ops/admin
- `require_gold_or_admin`: Blocks non-gold users, allows gold/admin
- `require_admin`: Blocks non-admin, allows admin only
- Test redirect behavior, message flashing, next URL preservation

#### Helper Functions (lines 120-142)
- `get_team_from_groups`: Extracts team number from group name
- `get_team_for_user`: Returns correct team or None
- Test edge cases: user in multiple teams, no team, invalid group names

## Medium Priority

### wipe_competition.py (0% coverage)

- Requires `--confirm` flag (safety check)
- Deletes all competition data (tickets, scores, incidents)
- Preserves team structure
- Creates audit log entry
- Test that it doesn't delete without confirmation

### init_teams.py (0% coverage)

- Creates teams from configuration
- Sets correct team numbers, names, max members
- Handles existing teams (skip or update)
- Test idempotency (running twice doesn't break)

### models.py (76% coverage - lines 38-48, 192-212)

- `AuditLog.log_action`: Creates audit entry with correct fields
- `SchoolInfo.__str__`: Returns expected string representation
- Model validation (if any custom validators)

### utils.py (66% coverage - lines 40-41, 89-91, 118-150)

- `format_duration`: Converts seconds to human-readable
- `parse_ticket_number`: Extracts team/sequence from ticket number
- `calculate_team_score`: Aggregates points correctly
- Edge cases: zero values, negative points, missing data

## Lower Priority

### authentik.py (0% coverage)

- `get_user_groups`: Fetches groups from Authentik API
- `sync_user_groups`: Updates local group cache
- Test with mocked API responses (success, failure, timeout)
- Test retry logic if implemented

### check_db_health.py (0% coverage)

- Checks database connectivity
- Reports table sizes, connection count
- Returns appropriate exit codes
- Test with mock database responses

### admin_mixins.py (0% coverage)

- `ReadOnlyAdminMixin`: Prevents edits in admin
- `AuditLogMixin`: Logs admin actions
- Test that save/delete are blocked for read-only models

### admin.py (75% coverage - lines 93-101, 181-196)

- `AuthentikAdminSite.has_permission`: Uses Authentik groups not is_staff
- Custom admin actions (if any)
- Test admin access control matches expected permissions

## Testing Approach Notes

1. **Use Django test client** for view tests - actual HTTP request/response
2. **Mock external services** (Discord API, Authentik API) - don't call real APIs
3. **Test authorization first** - ensure permission checks work before testing functionality
4. **Test error paths** - invalid input, missing data, permission denied
5. **Verify audit trails** - destructive operations should log
6. **Test with realistic fixtures** - multiple teams, various ticket states
