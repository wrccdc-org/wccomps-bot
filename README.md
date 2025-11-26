# WCComps Discord Bot

Competition team management and ticketing system with Discord bot, Django web interface, and Authentik SSO integration.

## Quick Start

### 1. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with:
- Discord bot token and guild ID
- Authentik OAuth credentials
- Database password
- Django secret key

### 2. Discord Bot Setup

1. Create bot at https://discord.com/developers/applications
2. Enable Server Members Intent and Message Content Intent
3. Invite with permissions: Manage Roles, Manage Channels, Send Messages, Use Slash Commands

### 3. Authentik Groups

Create these groups in Authentik:

- `WCComps_BlueTeam01` through `WCComps_BlueTeam50` - Team members
- `WCComps_Discord_Admin` - Full admin access
- `WCComps_Ticketing_Admin` - Ticket management
- `WCComps_Ticketing_Support` - Ticket support
- `WCComps_GoldTeam` - Team mappings and school info

### 4. Deploy

```bash
docker-compose up -d
```

Migrations and team initialization happen automatically.

### 5. Link Accounts

Everyone runs `/link` in Discord to connect their account to Authentik. Team assignment is automatic based on group membership.

## Commands

### User Commands
- `/link` - Connect Discord to Authentik account
- `/team-info` - View team information
- `/ticket <category> <description>` - Create support ticket

### Admin Commands

**Team Management (`/teams`):**
- `/teams list` - List all teams
- `/teams info <team_number>` - Team details
- `/teams unlink <users>` - Unlink Discord users
- `/teams remove <team_number>` - Remove team infrastructure
- `/teams reset <team_number>` - Full team reset

**Competition Management (`/competition`):**
- `/competition end-competition` - Cleanup all teams
- `/competition reset-blueteam-passwords` - Reset all passwords and export CSV
- `/competition toggle-blueteams <enable|disable>` - Enable/disable all accounts
- `/competition set-max-members <count>` - Set team member limit (1-20)
- `/competition set-start-time <datetime>` - Set start time
- `/competition set-end-time <datetime>` - Set end time
- `/competition start-competition` - Manually start competition
- `/competition set-apps <slugs>` - Set Authentik applications to control
- `/competition broadcast <target> <message>` - Broadcast to teams

**Ticketing (`/tickets`):**
- `/tickets create <team_number> <category> <description>` - Create ticket (admin only)
- `/tickets cancel <ticket_number> [reason]` - Cancel ticket (admin only)
- `/tickets reopen <ticket_number>` - Reopen ticket (admin only)

**Student Helpers (`/helpers`):**
- `/helpers add <user> <role_name>` - Add single student helper with Discord role
- `/helpers import <role>` - Import all users with a Discord role as helpers
- `/helpers list [status]` - List all student helpers
- `/helpers remove <user> [reason]` - Remove helper access
- `/helpers status <user>` - Check student helper status

**Admin (`/admin`):**
- `/admin sync-roles` - Sync roles from volunteer guild to competition guild

## Web Interface

Access levels based on Authentik groups:

**Team Members:**
- View tickets and point history at `/tickets/` and `/points/`
- Create tickets at `/create-ticket/`
- Access team packets at `/team-packets/`

**Ticketing Support:**
- Full ticket dashboard at `/ops/tickets/`
- Filter, sort, search, bulk operations
- Claim and resolve tickets

**Ticketing Admin:**
- All support features
- Create tickets for any team
- Cancel and reopen tickets
- Access Django admin ticket section

**GoldTeam:**
- All support features
- Manage group role mappings at `/ops/group-role-mappings/`
- Edit school info at `/ops/school-info/`
- Upload and distribute team packets at `/team-packets/ops/`

**Admin:**
- Full Django admin access at `/admin/`

## Ticket Workflow

**Create:** Team runs `/ticket` → Thread created in team category → Posted to dashboard

**Claim:** Support clicks "Claim" → Assigned and added to thread

**Resolve:** Support clicks "Resolve" → Enter notes → Points deducted → Thread archived

**Cancel:** Team can cancel unclaimed tickets (no penalty). Admin can cancel any ticket.

## Team Packet Distribution

Distribute pre-competition information packets to all teams on-demand.

**Features:**
- Upload single packet file (PDF, documents, etc.) up to 25 MB
- Email distribution to team contact emails (from SchoolInfo)
- Web download access for teams
- Track email delivery and download status
- Distribution statistics and reporting

**GoldTeam Workflow:**

1. Upload packet at `/team-packets/ops/upload/`
   - Set title and optional notes
   - Choose distribution methods (email and/or web)

2. Distribute immediately using "Distribute Now" button
   - Sends emails to all teams (if enabled)
   - Makes packet available for web download (if enabled)

3. Monitor distribution at `/team-packets/ops/`
   - View email send status
   - Track team downloads
   - Export distribution reports to CSV

**Team Member Access:**
- View available packets at `/team-packets/`
- Download packets directly from web interface
- Receive email notifications with download link

**Admin Features:**
- Full packet management at `/admin/packets/`
- Bulk distribution actions
- Retry failed emails
- Export distribution reports

**Email Configuration:**

Configure SMTP settings in `.env`:
```
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=noreply@wccomps.org
EMAIL_HOST_PASSWORD=your_password
DEFAULT_FROM_EMAIL=noreply@wccomps.org
```

For development/testing, use console backend:
```
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```
## Student Helper Management

Student helpers are temporary support staff for invitationals who are assigned Discord roles that grant access to team channels.

**Requirements:**
- User must first link Discord account with `/link`
- User must have either `WCComps_Ticketing_Support` OR `WCComps_Quotient_Injects` group in Authentik

**Workflow Options:**

**Option 1: Add Individual Helpers**
1. Admin runs `/helpers add @user "UCI Invitationals 2026"`
   - Discord role is created (if it doesn't exist) and immediately assigned
   - User gains access to team channels through the role
   - Assignment is tracked in database

**Option 2: Import from Existing Role (Recommended for bulk)**
1. Manually assign Discord role "UCI Invitationals 2026" to all helpers
2. Admin runs `/helpers import @UCI Invitationals 2026`
   - Finds all members with that role
   - Checks if each is linked and has required Authentik groups
   - Creates helper records for eligible users
   - Reports imported vs skipped with reasons

**During Event:**
- Helpers have the role and can access team channels

**Cleanup:**
- When `/competition end-competition` is run:
  - All helper roles are automatically removed
  - All assignments are marked as "removed" in the database
  - Audit logs are created for each removal

**Management:**
- **Add Single:** `/helpers add @user "Role Name"` - Add one helper at a time
- **Import Bulk:** `/helpers import @Role` - Import all users with an existing role
- **List:** `/helpers list` or `/helpers list active` - View all helpers and their status
- **Remove:** `/helpers remove @user "Reason"` - Manually remove helper role before competition ends
- **Status:** `/helpers status @user` - Check helper assignments and permissions

**Django Admin:**
- View and manage helper assignments at `/admin/competition/studenthelper/`
- See all active and removed assignments
- Audit trail with creation and removal timestamps

## Development

```bash
# Install dependencies
uv sync

# Run migrations
cd web && uv run python manage.py migrate

# Run web server
uv run python manage.py runserver

# Run bot (separate terminal)
cd bot && uv run python main.py

# Run tests
uv run pytest
```

## Configuration

Key environment variables:
- `DISCORD_BOT_TOKEN` - Bot token
- `DISCORD_GUILD_ID` - Guild ID
- `AUTHENTIK_URL` - Authentik server URL
- `AUTHENTIK_CLIENT_ID` / `AUTHENTIK_SECRET` - OAuth credentials
- `AUTHENTIK_TOKEN` - API token for password resets
- `BASE_URL` - Public URL for OAuth callbacks
- `DB_*` - Database configuration
- `EMAIL_*` - Email configuration for packet distribution (optional)

## Troubleshooting

**Bot not responding:** Check logs with `docker-compose logs bot`

**OAuth errors:** Verify `BASE_URL` matches domain and Authentik redirect URI

**Role assignment failing:** Check bot has Manage Roles permission and role hierarchy

**Ticket dashboard not updating:** Verify `DISCORD_TICKET_QUEUE_CHANNEL_ID` is set

## Clean Deployment Test

```bash
docker-compose down -v
docker-compose up -d
docker-compose logs web  # Watch initialization
```
