# WCComps Architecture & Implementation Details

Detailed architecture, workflows, and implementation notes for the WCComps competition management system.

## Architecture Overview

The system consists of three main components:

- **Django Web App**: Team linking OAuth flow, ticket viewing, admin interface, and API
- **Discord Bot**: Team management commands, ticket creation/resolution, and live dashboard
- **PostgreSQL**: Shared database for both components
- **Authentik**: OAuth2/OIDC provider for team authentication

## Authentication & Authorization

### Authentik Configuration

The system uses Authentik as the single source of truth for all authentication and permissions.

**OAuth2/OpenID Provider Setup:**
- Application Name: WCComps Team Portal
- Redirect URIs: `https://bot.wccomps.org/accounts/authentik/login/callback/`
- Client Type: Confidential
- Required Scopes: `openid`, `profile`, `email`, `groups`

**Important:** The `groups` scope is required for all permission checking. Without it, permission resolution will fail.

### Permission Groups

**Team Groups (WCComps_BlueTeam01-50):**
- Users can have any Authentik username
- Group membership determines team assignment
- When users run `/link`, they're assigned to team based on group
- Team members can:
  - Link Discord accounts via `/link` command
  - View tickets on web interface at `/tickets/`
  - View point history at `/points/`

**Permission Groups:**

**WCComps_Discord_Admin (Full Admin):**
- Full Django superuser access
- All team management commands
- All ticket management commands
- Access to Django admin interface

**WCComps_Ticketing_Admin (Ticket Manager):**
- Django staff access to ticket models
- Can create tickets for teams
- Can cancel tickets
- Can manually adjust points
- Access to ticket section in Django admin
- Access to web interface dashboard

**WCComps_Ticketing_Support (Ticket Support):**
- Can claim and resolve tickets via Discord
- Can add comments to tickets
- Can view ticket lists and point history
- Access to web interface dashboard
- Read-only Django admin access (via web dashboard)

**WCComps_GoldTeam (Infrastructure Team):**
- All ticketing support features
- Manage Discord group role mappings
- Edit school information for teams

All permissions are managed through Authentik groups - no manual Django user management needed.

## Linking Flow

Everyone (teams, support, admins) must link their Discord account to Authentik:

1. User runs `/link` in Discord
2. Bot generates unique token (15 min expiry) and OAuth URL
3. User clicks link and authenticates with their Authentik account (any username)
4. Django retrieves user's Authentik groups from OAuth response
5. Django checks for team group membership (`WCComps_BlueTeam01-50`):
   - **If found:** Extract team number, verify team not full, assign to team
   - **If not found:** Link without team assignment (support/admin user)
6. Django creates DiscordLink mapping Discord user → Authentik username (+ optional team)
7. **For team members:** Task queued to assign Discord roles (Team XX + Blueteam)
8. **For non-team users:** Permissions controlled via Authentik groups only
9. User receives confirmation

### Permission Resolution

- Bot checks DiscordLink to get user's Authentik username
- Looks up Authentik groups from SocialAccount:
  - Team assignment: `WCComps_BlueTeam01-50`
  - Admin access: `WCComps_Discord_Admin`
  - Ticket management: `WCComps_Ticketing_Admin`
  - Ticket support: `WCComps_Ticketing_Support`
  - Infrastructure: `WCComps_GoldTeam`
- Grants Discord command access based on group membership
- Falls back to Discord role checks if user not linked

## Multi-Guild Role Synchronization

The bot supports role synchronization between two Discord guilds:
- **Volunteer Guild** (404855247857778697): Where volunteers are initially granted roles
- **Competition Guild**: Where the competition takes place

**Role Mappings:**
- Operations team → BlackTeam
- Gold team → GoldTeam
- Red team → RedTeam
- White team → WhiteTeam
- Orange team → OrangeTeam

Role sync is **one-way** (Volunteer → Competition):
- Users with team roles in the volunteer guild automatically get them in the competition guild
- Users who lose roles in the volunteer guild have them removed from the competition guild
- Sync is triggered manually with `/admin sync-roles` command

## Database Schema

### Team Management
- **Team**: 50 teams (BlueTeam01-50) with Discord role/category IDs
- **DiscordLink**: Discord user to Authentik account mappings (optional team assignment)
- **LinkToken**: Temporary OAuth tokens (15 minute expiry)
- **LinkAttempt**: Audit log of all link attempts
- **AuditLog**: Admin action tracking

### Ticketing System
- **Ticket**: Support tickets with category, status, points, and assignment
- **TicketComment**: Comments on tickets (from teams or volunteers)
- **TicketAttachment**: File attachments stored in database
- **TicketHistory**: Audit log of ticket state changes
- **PointAdjustment**: Point penalties and bonuses
- **CommentRateLimit**: Rate limiting for ticket comments

### Bot Infrastructure
- **DiscordTask**: Task queue for bot operations (rate limit resilient)
- **BotState**: Bot state storage (dashboard message IDs, etc.)
- **DashboardUpdate**: Dashboard update tracking (for debouncing)
- **CompetitionConfig**: Competition timing and application control

## Ticket Categories

Configured in `web/core/tickets_config.py`:

1. **Service Scoring Validation** (0 points) - Verify scoring is working correctly
2. **Box Reset** (60 points) - Reset a service to clean state
3. **Scoring Service Check** (10 points) - Check if scoring service is running
4. **BlackTeam Phone Consultation** (100 points) - Phone support
5. **BlackTeam Hands-on Consultation** (200-300 points, variable) - In-person support
6. **Other** (0 points initially) - General issues, points adjusted manually by ticket lead

Variable cost categories default to lower value. Volunteers can override points during resolution.

## Ticketing Workflow Details

### Creating a Ticket

**Via Discord:**
1. Team member runs `/ticket <category> <description>` in Discord
2. Bot creates ticket in database with unique ticket number (format: `T050-001`)
3. Bot creates dedicated Discord thread in team's category
4. All team members automatically added to thread
5. Ticket posted to unified dashboard in #ticket-queue
6. Team can track status via Discord thread or web interface at `/tickets/`

**Via Web Interface:**
1. Team member navigates to `/create-ticket/`
2. Selects category and enters description
3. Ticket created and Discord thread generated automatically
4. If Quotient integration is configured, service selection dropdown is populated with infrastructure

### Claiming and Resolving

**Via Discord Thread Buttons:**
1. Support volunteer clicks "Claim" button in ticket thread or dashboard
2. Bot updates ticket status to "claimed" and assigns to volunteer
3. Volunteer automatically added to team's ticket thread
4. Volunteer works on issue and communicates in thread
5. Volunteer clicks "Resolve" button and enters resolution notes
6. Optional: For variable-point categories, volunteer enters point amount
7. Points automatically deducted from team
8. Ticket marked as resolved and thread archived after 60-second grace period

**Via Web Dashboard:**
1. Support volunteer navigates to `/ops/tickets/`
2. Uses filters to find tickets:
   - Status (open, claimed, resolved, cancelled)
   - Category
   - Team number
   - Assignee
   - Search by ticket number, title, or description
3. Clicks "Claim" button on open ticket
4. Works on issue (communicates via Discord thread or web comments)
5. Clicks ticket number to view detail page
6. Fills in resolution notes and clicks "Resolve"
7. For variable-point categories, enters point override
8. Points automatically deducted and ticket closed

### Ticket Cancellation

**By Team (Unclaimed Only):**
- Team members can cancel their own unclaimed tickets via "Cancel" button in Discord thread
- No point penalty for cancelling unclaimed tickets
- Claimed tickets must be cancelled by admin to prevent abuse

**By Admin:**
- Admins can cancel any ticket at any time via `/tickets cancel` command or web dashboard
- Optional reason can be provided
- Ticket status changed to "cancelled"
- Thread archived after 60-second grace period
- No point penalty

### Ticket Reopening

- Admins can reopen resolved or cancelled tickets via `/tickets reopen` command
- Ticket status changed back to "open"
- Points are not refunded automatically (manual adjustment needed)
- Thread remains archived (must be manually unarchived if needed)

### Unified Dashboard

The unified dashboard in #ticket-queue provides:
- Real-time view of all open and claimed tickets
- Color-coded status indicators:
  - Red background: Open tickets
  - Orange background: Claimed tickets
  - Green background: Resolved tickets (shown briefly before removal)
- Stale ticket warnings:
  - ⚠️ icon for tickets claimed >30 minutes
  - 🔥 icon for tickets claimed >1 hour
  - 💀 icon for tickets claimed >2 hours
- Interactive buttons for claim/resolve actions
- Automatic updates when ticket status changes
- Sorted by: status (open first), then staleness, then team number
- Filter controls to show only open or claimed tickets
- Shows ticket number, team, category, assignee, and time information

## Ticket Attachments and Comments

### Attachments
- Team members and support can attach files directly in Discord ticket threads
- Files are downloaded and stored in database as binary data
- Maximum file size: 10MB per file
- Supported file types: all (stored as binary with MIME type)
- Bot reacts with 📎 emoji to confirm successful upload
- Attachments viewable on web interface at ticket detail page

### Comments
- All messages in ticket threads are automatically synced to database
- Comments visible on web interface for full ticket history
- Rate limiting: 5 comments per minute per ticket, 10 comments per minute per user
- Edit tracking: Edits to Discord messages sync to database
- Deletion tracking: Deleted messages marked as "[Message deleted]"
- Web-posted comments are sent to Discord thread automatically

### Rate Limiting
- Implemented via `CommentRateLimit` model
- Tracks message timestamps per user and per ticket
- Ticket-level limit: 5 comments per minute per ticket
- User-level limit: 10 comments per minute per user (across all tickets)
- Violating messages are deleted with ephemeral warning
- Prevents spam and abuse in ticket threads

## Password Management

### Resetting BlueTeam Passwords

The `/competition reset-blueteam-passwords` command allows WCComps_Discord_Admin members to reset all blueteam account passwords at once.

**Requirements:**
- User must be in `WCComps_Discord_Admin` Authentik group
- `AUTHENTIK_TOKEN` environment variable must be configured with valid API token
- Generate token at: `https://auth.wccomps.org/if/admin/#/core/tokens`

**Workflow:**
1. Admin runs `/competition reset-blueteam-passwords` in Discord
2. Bot generates readable passphrase-style passwords for blueteam01-blueteam50
3. Bot calls Authentik API to reset each password
4. Bot creates CSV file with username and password
5. CSV file sent as ephemeral Discord attachment (only visible to admin)
6. Action logged to ops channel and audit log

**Password Format:**
Passwords are generated using the **EFF Long Wordlist** (7,776 words) via `xkcdpass` library.

Format: `Word-Word` with a random number (100-999) AND special character (!@#$%&*+) combined together and interspersed at a random position.

Examples: `Renovate-542#-Unleash` or `315!-Lunchbox-Molecule`

**CSV Format:**
```csv
Username,Password
blueteam01,Renovate-542#-Unleash
blueteam02,Sleeping-@789-Rewrite
...
```

**Security Notes:**
- CSV file is sent as ephemeral message (only admin can see)
- All password resets are logged in audit trail
- Passwords use EFF Long Wordlist with cryptographically secure randomness
- Each password provides ~41 bits entropy, exceeding NIST guidelines
- Passwords are 19-25 characters - secure yet quick to type

## Competition Management

### Automatic Application Control

The system can automatically enable/disable Authentik applications based on competition timing:

**Configuration:**
- Set start time: `/competition set-start-time <datetime>`
- Set end time: `/competition set-end-time <datetime>`
- Set applications to control: `/competition set-apps <slugs>` (comma-separated)

**Behavior:**
- Background task checks every minute
- At start time: enables all configured applications
- At end time: disables all configured applications
- Manual override: `/competition start-competition` to enable immediately
- Note: Blueteam account toggling is separate via `/competition toggle-blueteams` command

**Implementation:**
- Uses `CompetitionConfig` model to store timing
- `CompetitionTimer` background task polls every minute
- Calls Authentik API to update policy bindings
- Logs all actions to ops channel

### Team Infrastructure Management

**Team Setup:**
Each team gets:
- Discord role (Team XX)
- Discord category (team XX or team X format)
- Three channels within category:
  - team-chat (text)
  - voice (voice)
  - general (text)

**Setup Command:**
- Run `/teams` commands to create infrastructure as needed
- Bot searches for categories by both "team X" and "team XX" formats
- Automatically creates missing roles and channels
- Self-healing: recreates infrastructure if partially deleted

**Removal:**
- `/teams remove <team_number>` - Remove infrastructure (Team 1 protected)
- `/competition end-competition` - Remove ALL teams including Team 1
- Channels, roles, and categories are deleted
- Database records remain for audit trail

## Web Interface Details

### Operations Dashboard (`/ops/tickets/`)

Full-featured ticket management interface for support and admin users.

**Features:**
- Real-time filtering by status, category, team, assignee
- Search by ticket number, title, or description
- Sort by any column (team, category, status, assigned, created)
- Bulk operations: claim multiple tickets, resolve multiple tickets
- Adjustable pagination: 25/50/100/200 results per page
- Debounced search: 800ms delay to prevent excessive requests
- Focus preservation: search field maintains cursor position after reload
- Auto-submit on filter changes
- Keyboard shortcut: `/` to focus search field

**URL Parameters:**
All filter and sort state is preserved in URL for bookmarking and sharing:
- `status=open|claimed|resolved|cancelled|all`
- `category=<category_id>|all`
- `team=<team_number>`
- `assignee=<username>|unassigned`
- `search=<query>`
- `sort=<field>|-<field>` (minus prefix for descending)
- `page=<number>`
- `page_size=25|50|100|200`

**Stale Ticket Indicators:**
- No indicator: claimed <30 minutes ago
- "STALE" label: claimed 30-60 minutes ago
- Additional visual indicators for >1 hour, >2 hours

### Ticket Detail Page (`/ops/ticket/<ticket_number>/`)

**Sections:**
- Ticket Information: all metadata and status
- Actions: claim/unclaim/resolve buttons based on status
- Comments: all thread messages and web comments
- Add Comment: post to ticket thread (if not resolved/cancelled)
- Attachments: download files uploaded via Discord
- History: complete audit trail of all ticket state changes

**Thread Warning:**
If ticket's Discord thread failed to create, shows prominent warning that team can only interact via web interface.

### Team Ticket Views

**Team Tickets (`/tickets/`):**
- Team members see only their own team's tickets
- Filtered automatically by team assignment
- Cannot see other teams' tickets
- Can create new tickets via link to `/create-ticket/`

**Ticket Detail (`/tickets/<id>/`):**
- Team members can view their own ticket details
- Can see comments from support and team
- Can view attachments
- Cannot claim, resolve, or modify tickets

**Point History (`/points/`):**
- View all point adjustments for team
- Shows ticket-related penalties
- Shows manual point adjustments by admins
- Running total

## Troubleshooting Details

### Bot Not Responding to Commands

**Symptoms:** Slash commands don't appear or don't execute

**Diagnosis:**
1. Check bot is online: `docker-compose ps`
2. Check logs: `docker-compose logs bot`
3. Verify bot has correct intents enabled in Discord Developer Portal
4. Check command sync logs at startup

**Common Causes:**
- Bot restarted but commands not synced (wait ~1 minute)
- Guild ID mismatch in environment variables
- Bot missing permissions in guild
- Bot not in guild

### OAuth Flow Errors

**Symptoms:** "Redirect URI mismatch" or "Invalid client" errors

**Diagnosis:**
1. Verify `BASE_URL` in `.env` matches your domain exactly
2. Check Authentik redirect URI matches: `{BASE_URL}/accounts/authentik/login/callback/`
3. Verify client ID and secret are correct
4. Ensure `groups` scope is enabled in Authentik provider

**Common Causes:**
- BASE_URL has trailing slash (remove it)
- Using http:// in production instead of https://
- Client secret was regenerated but not updated in .env
- Groups scope not enabled (breaks all permission checks)

### Role Assignment Not Working

**Symptoms:** Users linked but don't receive Discord roles

**Diagnosis:**
1. Check `DiscordTask` queue in Django admin: `/admin/core/discordtask/`
2. Look for failed tasks with error messages
3. Verify bot has Manage Roles permission
4. Check bot role is higher than team roles in Discord hierarchy
5. Check bot logs for rate limit or permission errors

**Common Causes:**
- Bot role positioned below team roles (can't assign)
- Manage Roles permission not granted
- Rate limiting from Discord (will retry automatically)
- Guild not found (wrong DISCORD_GUILD_ID)

### Queue Processor Errors

**Symptoms:** Tasks stuck in "ready" status, never complete

**Diagnosis:**
1. Check bot logs: `docker-compose logs bot`
2. Check database connection from bot
3. Look for failed tasks in Django admin
4. Check for Python exceptions in task processing

**Recovery:**
- Failed tasks can be retried using Django admin bulk action
- Delete permanent failures after investigation
- Check for network issues between bot and database

### Ticket Dashboard Not Updating

**Symptoms:** #ticket-queue channel doesn't show tickets or doesn't update

**Diagnosis:**
1. Verify `DISCORD_TICKET_QUEUE_CHANNEL_ID` is set correctly in `.env`
2. Check bot has permissions to post in the channel
3. Check `BotState` model in Django admin for dashboard message ID
4. Look for "dashboard" related errors in bot logs
5. Check `DashboardUpdate` model for update tracking

**Common Causes:**
- Wrong channel ID configured
- Bot lacks Send Messages permission in channel
- Dashboard message was deleted manually (will recreate)
- Rate limiting from Discord (updates debounced)

**Recovery:**
- Delete `BotState` record with type "unified_dashboard_message" to force recreation
- Restart bot to reinitialize dashboard

### Category Not Found Errors

**Symptoms:** Bot can't find team category when creating threads

**Diagnosis:**
1. Bot searches for both "team X" and "team XX" formats
2. Ensure categories are named properly (lowercase "team 01", "team 02", etc.)
3. Check `Team` model has `discord_category_id` populated
4. Verify category actually exists in Discord

**Recovery:**
- Manually set category ID in Django admin
- Run `/teams` commands to recreate missing infrastructure
- Ensure category names match expected format

### Database Connection Errors

**Symptoms:** "Connection refused" or "Authentication failed" errors

**Diagnosis:**
1. Ensure PostgreSQL is running: `docker-compose ps postgres`
2. Check database credentials in `.env`
3. Verify `DB_HOST=postgres` in docker-compose environment (not localhost)
4. Check PostgreSQL logs: `docker-compose logs postgres`

**Common Causes:**
- Wrong password in .env
- DB_HOST set to localhost instead of postgres
- PostgreSQL container not started
- Network issues between containers

## Security Implementation

### All Pages Protected by Authentik
- Middleware enforces authentication on every page
- Unauthenticated users redirected to Authentik login
- Session cookies tied to Authentik OAuth session

### No Django-Managed Users
- Authentik is the single source of truth
- No Django user passwords stored locally
- All authentication via OAuth2/OIDC flow

### Permission Updates
- Change groups in Authentik → permissions update on next command/login
- No cache invalidation needed (groups checked on each request)
- Removing user from group immediately revokes access

### Scoped Access Controls
- Team members can only view their own team's tickets and points
- Ticketing support can work on any ticket via Discord commands
- Ticketing admins can manage tickets in Django admin
- Discord admins have full superuser access

### Production Security Features
When `DJANGO_DEBUG=False`:
- `SESSION_COOKIE_SECURE = True` - Cookies only sent over HTTPS
- `CSRF_COOKIE_SECURE = True` - CSRF cookies only sent over HTTPS
- `SECURE_SSL_REDIRECT = False` - SSL redirect handled by reverse proxy (Traefik)
- `SECURE_HSTS_SECONDS = 31536000` - HSTS enabled for 1 year
- `SECURE_HSTS_INCLUDE_SUBDOMAINS = True` - HSTS includes subdomains
- `SECURE_HSTS_PRELOAD = True` - Enable HSTS preload

Ensure your reverse proxy (Traefik, nginx, Caddy, etc.) handles TLS termination and HTTP→HTTPS redirect.

## Task Queue & Rate Limiting

### DiscordTask Model
- All Discord API operations queued as tasks
- Prevents bot from blocking on slow API calls
- Resilient to rate limits with exponential backoff

**Task States:**
- `ready`: Waiting to execute (ready_at <= now)
- `pending`: Executing or waiting for rate limit cooldown
- `completed`: Successfully executed
- `failed`: Failed after max retries (default 5)

**Retry Logic:**
- Exponential backoff: 2^retry_count seconds (first retry: 2s, second: 4s, third: 8s, etc.), capped at 300s
- Discord rate limit headers respected
- Tasks automatically retried on transient errors

### Queue Processor
- Polls database every 2 seconds for ready tasks
- Processes up to 10 tasks per poll
- Oldest tasks (by created_at) processed first
- Logs all task execution to ops channel on failure

## Management Commands

These commands are rarely needed (most operations done via Discord or Django admin):

```bash
# Nuclear option: wipe all competition data (use at end of competition)
docker-compose exec web uv run python manage.py wipe_competition --confirm

# Manual team initialization (only needed if automatic init failed)
docker-compose exec web uv run python manage.py init_teams
```

**Warning:** `wipe_competition` deletes ALL competition data including teams, links, tickets, and audit logs. Use only when starting fresh competition.
