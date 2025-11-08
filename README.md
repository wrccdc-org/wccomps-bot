# WCComps Discord Bot

Competition team management and ticketing system with Discord bot, Django web interface, and Authentik SSO integration.

## Architecture

- **Django Web App**: Team linking OAuth flow, ticket viewing, admin interface, and API
- **Discord Bot**: Team management commands, ticket creation/resolution, and live dashboard
- **PostgreSQL**: Shared database for both components
- **Authentik**: OAuth2/OIDC provider for team authentication (team01-team50 accounts)

## Quick Start

### 1. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your configuration:
- Discord bot token and guild ID
- Authentik OAuth client credentials
- Database password
- Django secret key

### 2. Discord Bot Setup

1. Create bot at https://discord.com/developers/applications
2. Enable Server Members Intent and Message Content Intent
3. Add bot token and guild ID to `.env`
4. Invite with permissions: Manage Roles, Manage Channels, Send Messages, Use Slash Commands
5. Set `DISCORD_LOG_CHANNEL_ID` to your ops log channel ID

### 3. Authentik Configuration

1. Create OAuth2/OpenID Provider application
   - Name: WCComps Team Portal
   - Redirect URIs: `https://bot.wccomps.org/accounts/authentik/login/callback/`
   - Client Type: Confidential
   - Add client ID and secret to `.env`

2. Configure provider scopes: `openid`, `profile`, `email`, `groups`
   - **Important:** The `groups` scope is required for all permission checking

3. Create groups in Authentik:

   **Team Groups (WCComps_BlueTeam01-50):**
   - Create groups: `WCComps_BlueTeam01` through `WCComps_BlueTeam50`
   - Add team members to their respective team group
   - Users can have any Authentik username
   - Group membership determines team assignment
   - When users run `/link`, they're assigned to team based on group
   - Team members can:
     - Link Discord accounts (via `/link` command)
     - View tickets on web interface at `/tickets/`
     - View point history at `/points/`

   **Permission Groups:**

   **WCComps_Discord_Admin** (Full Admin):
   - Full Django superuser access
   - All team management commands
   - All ticket management commands
   - Access to Django admin interface

   **WCComps_Ticketing_Admin** (Ticket Manager):
   - Django staff access to ticket models
   - Can create tickets for teams
   - Can cancel tickets
   - Can manually adjust points
   - Access to ticket section in Django admin
   - Access to web interface dashboard

   **WCComps_Ticketing_Support** (Ticket Support):
   - Can claim and resolve tickets via Discord
   - Can add comments to tickets
   - Can view ticket lists and point history
   - Access to web interface dashboard
   - Read-only Django admin access (via web dashboard)

   All permissions are managed through Authentik groups - no manual Django user management needed.

### 4. Deploy with Docker

```bash
# Build and start all services
docker-compose up -d

# Check logs (migrations and team initialization happen automatically)
docker-compose logs -f web
docker-compose logs -f bot

# Access services
# Web: http://localhost:8000
# Admin: http://localhost:8000/admin (login with Authentik WCComps_Discord_Admin group user)
# PostgreSQL: localhost:5432
```

The web container automatically on first startup:
- Runs database migrations
- Initializes 50 teams (BlueTeam01-50)

No Django users are created - all authentication goes through Authentik. Users in the `WCComps_Discord_Admin` group automatically get Django admin access.

### 5. Link Discord Accounts to Authentik

**Everyone must run `/link` to connect their Discord account to Authentik:**

**For Team Members:**
1. Admin adds user to appropriate team group (e.g., `WCComps_BlueTeam04`)
2. User creates Authentik account (any username)
3. User runs `/link` in Discord
4. User authenticates with their Authentik account
5. System detects `WCComps_BlueTeam04` group membership
6. Discord role and team channels assigned automatically
7. User can view tickets and points on web interface

**For Support Staff:**
1. User creates Authentik account (any username)
2. Admin adds user to `WCComps_Ticketing_Support` group
3. User runs `/link` in Discord
4. User authenticates with their Authentik account
5. Can claim/resolve tickets via Discord commands

**For Admins:**
1. User creates Authentik account (any username)
2. Admin adds user to `WCComps_Discord_Admin` or `WCComps_Ticketing_Admin` group
3. User runs `/link` in Discord
4. User authenticates with their Authentik account
5. Permissions granted based on group membership

### 6. Setup Discord Infrastructure

In Discord, run: `/teams`, `/tickets`, or `/competition` commands to set up team roles and channels as needed.

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

## Commands

### User Commands
- `/link` - **[REQUIRED]** Generate OAuth link to connect Discord to Authentik account
- `/team-info` - View your current team information and members
- `/ticket <category> <description>` - Create a support ticket

### Admin Commands

**Team Management:**
- `/teams list` - List all teams with member counts
- `/teams info <team_number>` - Detailed info about specific team
- `/teams unlink <users>` - Unlink one or more Discord users from their teams
- `/teams remove <team_number>` - Remove team infrastructure (Team 1 category/channels protected)
- `/teams reset <team_number>` - Comprehensive team reset (unlinks users, resets password, revokes sessions, optionally recreates channels)

**Competition Management:**
- `/competition end-competition` - Cleanup all teams at end of competition (deletes ALL infrastructure including Team 01)
- `/competition reset-blueteam-passwords` - Reset passwords for all blueteam01-blueteam50 accounts and export CSV
- `/competition toggle-blueteams <enable|disable>` - Enable or disable all blueteam accounts
- `/competition set-max-members <count>` - Set maximum members per team globally (1-20)
- `/competition set-start-time <datetime>` - Set competition start time for auto-enabling applications
- `/competition set-end-time <datetime>` - Set competition end time for auto-disabling applications
- `/competition start-competition` - Manually start competition (enable applications and accounts)
- `/competition set-apps <slugs>` - Set which Authentik applications to control
- `/competition broadcast <target> <message>` - Broadcast message to announcements, all teams, or specific teams (e.g., "1,3,5-10")

**General Admin:**
- `/admin sync-roles` - Synchronize team roles from volunteer guild to competition guild (one-way sync)

**Ticketing:**
- `/tickets create <team_number> <category> <description>` - Create ticket for a team
- `/tickets list [status] [team_number]` - List and filter tickets
- `/tickets resolve <ticket_id> <notes> [points]` - Resolve ticket with optional point override (use dashboard button instead)
- `/tickets cancel <ticket_id> [reason]` - Cancel ticket without point penalty
- `/tickets reassign <ticket_id> <support_user>` - Reassign ticket to different support volunteer
- `/tickets reopen <ticket_id>` - Reopen a resolved ticket

**Team Commands:**
- `/ticket-cancel <ticket_id>` - Cancel your own unclaimed ticket (no point penalty)

## Web Interface

All web pages require Authentik authentication. Access level based on group membership:

**Team Members (WCComps_BlueTeam01-50):**
- View their team's tickets and points
- Create tickets via Discord `/ticket` command

**Ticketing Support (WCComps_Ticketing_Support):**
- Dashboard showing ticketing operations access
- Discord commands for ticket management

**Ticketing Admin (WCComps_Ticketing_Admin):**
- Dashboard with link to ticket management in Django admin
- Full ticket CRUD operations via web interface
- Discord commands for ticket management

**Admin (WCComps_Discord_Admin):**
- Full Django admin access
- All features available

**Available URLs:**
- **Home**: `/` - Dashboard with navigation (redirects here after login)
- **Team Tickets**: `/tickets/` - View team's tickets (team members only)
- **Ticket Details**: `/tickets/<id>/` - View ticket details and comments (team members only)
- **Point History**: `/points/` - View team's point adjustments (team members only)
- **Django Admin**: `/admin` - Full admin interface (admins) or ticket management (ticketing admins)
- **OAuth Flow**: `/auth/link?token=...` - Discord linking entry point (public, redirects to Authentik)

## Development

### Local Development Without Docker

```bash
# Install dependencies
uv sync

# Start PostgreSQL (or use local instance)
docker-compose up -d postgres

# Run migrations
cd web
uv run python manage.py migrate

# Start web server
uv run python manage.py runserver

# In another terminal, run bot
cd bot
uv run python main.py
```

Login via Authentik with a user in the `WCComps_Discord_Admin` group to get admin access.

### Testing

```bash
# Run test suite
uv run pytest

# Run with coverage
cd bot && uv run pytest --cov=. --cov-report=html
```

See `bot/tests/README.md` for details. Tests run automatically during deployment.

### Management Commands

These commands are rarely needed (most operations done via Discord or Django admin):

```bash
# Nuclear option: wipe all competition data (use at end of competition)
docker-compose exec web uv run python manage.py wipe_competition --confirm

# Manual team initialization (only needed if automatic init failed)
docker-compose exec web uv run python manage.py init_teams
```

## Configuration

Key environment variables (see `.env.example` for full list):

- `DISCORD_BOT_TOKEN` - Discord bot token
- `DISCORD_GUILD_ID` - Competition guild ID
- `DISCORD_LOG_CHANNEL_ID` - Channel for ops logging
- `AUTHENTIK_URL` - Authentik server URL
- `AUTHENTIK_CLIENT_ID` - OAuth client ID
- `AUTHENTIK_SECRET` - OAuth client secret
- `BASE_URL` - Public URL for OAuth callbacks
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` - Database configuration

## Linking Flow

**Everyone (teams, support, admins) must link their Discord account to Authentik:**

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

**Permission Resolution:**
- Bot checks DiscordLink to get user's Authentik username
- Looks up Authentik groups from SocialAccount:
  - Team assignment: `WCComps_BlueTeam01-50`
  - Admin access: `WCComps_Discord_Admin`
  - Ticket management: `WCComps_Ticketing_Admin`
  - Ticket support: `WCComps_Ticketing_Support`
- Grants Discord command access based on group membership
- Falls back to Discord role checks if user not linked

## Database Schema

**Team Management:**
- **Team**: 50 teams (BlueTeam01-50) with Discord role/category IDs
- **DiscordLink**: Discord user to Authentik account mappings (optional team assignment)
- **LinkToken**: Temporary OAuth tokens (15 minute expiry)
- **LinkAttempt**: Audit log of all link attempts
- **AuditLog**: Admin action tracking

**Ticketing System:**
- **Ticket**: Support tickets with category, status, points, and assignment
- **TicketComment**: Comments on tickets (from teams or volunteers)
- **TicketAttachment**: File attachments (model exists, not yet implemented)
- **TicketHistory**: Audit log of ticket state changes
- **PointAdjustment**: Point penalties and bonuses

**Bot Infrastructure:**
- **DiscordTask**: Task queue for bot operations (rate limit resilient)
- **BotState**: Bot state storage (dashboard message IDs, etc.)
- **DashboardUpdate**: Dashboard update tracking (for debouncing)

## Ticket Categories

The system supports 6 ticket categories configured in `web/core/tickets_config.py`:

1. **Service Scoring Validation** (0 points) - Verify scoring is working correctly
2. **Box Reset** (60 points) - Reset a service to clean state
3. **Scoring Service Check** (10 points) - Check if scoring service is running
4. **BlackTeam Phone Consultation** (100 points) - Phone support
5. **BlackTeam Hands-on Consultation** (200-300 points, variable) - In-person support
6. **Other** (0 points initially) - General issues, points adjusted manually by ticket lead

Variable cost categories default to lower value. Volunteers can override points during resolution.

## Ticketing Workflow

### Creating a Ticket
1. Team member runs `/ticket <category> <description>` in Discord
2. Bot creates ticket in database and posts to #ticket-queue channel
3. Ticket appears with color-coded embed based on status
4. Team can view ticket status on web interface at `/tickets/`

### Claiming and Resolving
1. Volunteer clicks "Claim" button in ticket embed
2. Bot updates ticket status to "claimed" and shows volunteer's name
3. Volunteer works on issue
4. Volunteer clicks "Start Work" to mark in progress
5. Volunteer runs `/tickets resolve <id> <notes>` to close ticket
6. Points automatically deducted from team
7. Ticket marked as resolved

### Dashboard
- Live ticket queue displayed in #ticket-queue channel
- Shows all open and claimed tickets
- Organized by category and status
- Interactive buttons for claiming and starting work
- Updates automatically when ticket status changes

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
Passwords are generated using the **EFF Long Wordlist** (7,776 words) in the format: `Word-Word` with a random number (100-999) AND special character (!@#$%&*+) combined together and interspersed at a random position.

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
- Passwords use EFF Long Wordlist via `xkcdpass` library with cryptographically secure randomness
- Each password provides ~41 bits entropy, exceeding NIST guidelines for competition accounts
- Passwords are 19-25 characters - secure yet quick to type during competition

## Troubleshooting

### Bot not responding to commands
- Check bot is online: `docker-compose ps`
- Check logs: `docker-compose logs bot`
- Verify bot has correct intents enabled
- Ensure commands are synced: restart bot container

### OAuth flow errors
- Verify `BASE_URL` matches your domain
- Check Authentik redirect URI matches: `{BASE_URL}/accounts/authentik/login/callback/`
- Verify Authentik client ID and secret are correct
- Ensure `groups` scope is enabled in Authentik provider

### Database connection errors
- Ensure PostgreSQL is running: `docker-compose ps postgres`
- Check database credentials in `.env`
- Verify `DB_HOST=postgres` in docker-compose environment

### Role assignment not working
- Check `DiscordTask` queue in Django admin
- Verify bot has Manage Roles permission
- Ensure bot role is higher than team roles in Discord hierarchy
- Check bot logs for rate limit or permission errors

### Queue processor errors
- Check bot logs: `docker-compose logs bot`
- Verify database connection is working
- Check for failed tasks in Django admin at web interface: `/admin/core/discordtask/`
- Retry failed tasks using admin action

### Ticket queue channel not updating
- Verify `DISCORD_TICKET_QUEUE_CHANNEL_ID` is set correctly
- Check bot has permissions to post in the channel
- Check `DashboardUpdate` model in Django admin
- Look for "dashboard" related errors in bot logs

### Category not found errors
- Bot searches for both "team X" and "team XX" formats
- Ensure categories are named properly (lowercase "team 01", "team 02", etc.)
- Check `Team` model has `discord_category_id` populated
- Manually set category ID in Django admin if needed

### Clean deployment test
```bash
# Stop and remove all data
docker-compose down -v

# Start fresh (migrations, superuser, and teams initialize automatically)
docker-compose up -d

# Check logs to verify initialization
docker-compose logs web
```

## Security Notes

- **All web pages protected by Authentik** - Middleware enforces authentication on every page
- **No Django-managed users** - Authentik is the single source of truth for all authentication
- **All permissions via Authentik groups** - Team assignment, admin access, ticketing permissions all controlled by group membership
- **Automatic permission updates** - Change groups in Authentik → permissions update on next command/login
- **Scoped access controls:**
  - Team members can only view their own team's tickets and points
  - Ticketing support can work on any ticket via Discord commands
  - Ticketing admins can manage tickets in Django admin
  - Discord admins have full superuser access
- Production deployment automatically enables HTTPS-only cookies
- CSRF protection enabled by default
- HSTS headers set for 1 year in production
- All sensitive data stored in environment variables
- OAuth tokens expire after 15 minutes
- Database credentials never exposed to client
- Removing user from any permission group immediately revokes access on next login

## Production Deployment

When `DJANGO_DEBUG=False`, the following security features are automatically enabled:
- `SESSION_COOKIE_SECURE = True` - Cookies only sent over HTTPS
- `CSRF_COOKIE_SECURE = True` - CSRF cookies only sent over HTTPS
- `SECURE_SSL_REDIRECT = True` - Redirect HTTP to HTTPS
- `SECURE_HSTS_SECONDS = 31536000` - HSTS enabled for 1 year
- `SECURE_HSTS_INCLUDE_SUBDOMAINS = True` - HSTS includes subdomains
- `SECURE_HSTS_PRELOAD = True` - Enable HSTS preload

Ensure your reverse proxy (nginx, Caddy, etc.) handles TLS termination.
