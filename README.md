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

**Admin (`/admin`):**
- `/admin sync-roles` - Sync roles from volunteer guild to competition guild

## Web Interface

Access levels based on Authentik groups:

**Team Members:**
- View tickets and point history at `/tickets/` and `/points/`
- Create tickets at `/create-ticket/`

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

**Admin:**
- Full Django admin access at `/admin/`

## Ticket Workflow

**Create:** Team runs `/ticket` → Thread created in team category → Posted to dashboard

**Claim:** Support clicks "Claim" → Assigned and added to thread

**Resolve:** Support clicks "Resolve" → Enter notes → Points deducted → Thread archived

**Cancel:** Team can cancel unclaimed tickets (no penalty). Admin can cancel any ticket.

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
