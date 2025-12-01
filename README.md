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

**Orange Team (`/orange`):**
- `/orange submit <team> <points> <check_type> <description>` - Submit scoring adjustment
- `/orange list [status]` - List pending/approved adjustments
- `/orange list-types` - List available check types
- `/orange add-type <name> <default_points>` - Add a new check type
- `/orange remove-type <name>` - Remove a check type

**Inject Grading (`/inject`):**
- `/inject list` - List available injects from Quotient
- `/inject grade <inject_id> <team> <points> [notes]` - Grade an inject for a team
- `/inject list-grades [inject_id] [status]` - List grades for an inject

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

## User Guide

### Quick Start by Role

#### Blue Team (Competition Participants)

**Getting Started:**
1. Run `/link` in Discord to connect your account
2. Join your team's voice and text channels
3. Access the web interface at the competition URL

**Submit Incident Reports:**
1. Navigate to "Incidents" in the header
2. Click "Submit Incident Report"
3. Select target box (destination IP auto-fills)
4. Choose source IP and attack type
5. Describe what you detected
6. Submit (goes to Gold Team for review)

**View Your Incidents:**
- Navigate to "Incidents" to see all your team's submissions
- Review past reports to avoid duplicates

**Create Support Tickets:**
- Run `/ticket <category> <description>` in Discord
- Or use the web interface at `/create-ticket/`
- Track status in Discord thread or web dashboard

**Download Team Packets:**
- Navigate to `/team-packets/` to view available materials
- Download pre-competition information and resources

**Restrictions:**
- Cannot view leaderboard during competition (use Quotient)
- Cannot see other teams' data

---

#### Red Team (Attackers)

**Getting Started:**
1. Run `/link` in Discord to connect your account
2. Access the web interface at the competition URL

**Submit Findings:**
1. Navigate to "Red Team Findings" in the header
2. Click "Submit Finding"
3. Select target team and box
4. Enter source IP and attack type
5. Describe the attack method and result
6. Submit (goes to Gold Team for approval)

**View All Findings:**
- Navigate to "Red Team Findings" to see ALL submissions from ALL red team members
- Filter by target team, attack type, or submitter
- Coordinate with team to avoid duplicate attacks

**Restrictions:**
- Cannot see if findings were matched to Blue Team incidents
- Cannot see approval status
- Cannot view leaderboard

---

#### Gold Team (Competition Organizers/Judges)

**Getting Started:**
1. Run `/link` in Discord to connect your account
2. Access the Scoring section at `/scoring/`

**Review Incidents (Must Review All):**
1. Navigate to Scoring > Review Incidents
2. View each incident report in the queue
3. Check for matching Red Team findings (auto-suggested by IP/time)
4. Match incident to finding or reject if invalid
5. Track review progress

**Approve Red Team Findings (Spot Check):**
1. Navigate to Scoring > Review Red Team
2. Scan submissions for validity
3. Flag suspicious entries for detailed review
4. Bulk approve remaining entries

**Review Orange Team Adjustments:**
1. Navigate to Scoring > Orange Team
2. Review adjustment submissions (team, points, reason)
3. Approve or reject individual or bulk items

**Review Inject Grades:**
1. Navigate to Scoring > Inject Grading
2. Spot-check grades for consistency
3. Flag outliers for review
4. Bulk approve when satisfied

**View Leaderboard:**
- Navigate to Scoring > Leaderboard for current standings
- See score breakdown by category

**Manage Team Info:**
- Navigate to "Team Mappings" to view participant assignments
- Navigate to "School Info" to manage contact information

---

#### White Team (Inject Graders)

**Getting Started:**
1. Run `/link` in Discord to connect your account
2. Access the Scoring section at `/scoring/`

**Submit Inject Grades:**
1. Navigate to Scoring > Inject Grading
2. Select the inject to grade
3. Select the team
4. Enter score and optionally max points
5. Submit (goes to Gold Team for approval)
6. Track grading progress

**View Leaderboard:**
- Navigate to Scoring > Leaderboard for current standings

**Restrictions:**
- Cannot review incidents or red findings
- Cannot submit orange adjustments

---

#### Orange Team (Bonus/Penalty Adjustments)

**Getting Started:**
1. Run `/link` in Discord to connect your account
2. Access the web interface at the competition URL

**Submit Point Adjustments:**
1. Navigate to Scoring > Orange Team
2. Click "Submit Adjustment"
3. Select target team
4. Choose or create check type (e.g., "Customer service call", "Rule violation")
5. Enter point value (positive for bonus, negative for penalty)
6. Provide justification/reason
7. Submit (goes to Gold Team for approval)

**View Your Submissions:**
- Navigate to Scoring > Orange Team to see your adjustments
- Check approval status

**Common Check Types:**
- Customer service call answered
- Network diagram completed
- Password reset assistance
- Rule violation (negative points)
- Professional behavior bonus
- (New types created on first use)

**Restrictions:**
- Cannot approve your own adjustments
- Cannot view leaderboard

---

#### Ticketing Support

**Getting Started:**
1. Run `/link` in Discord to connect your account
2. Access the ticket dashboard at `/ops/tickets/`

**View Ticket Queue:**
- Dashboard shows all tickets with filters
- Sort by age, team, category, status
- Search by ticket number or description
- Identify stale tickets needing attention

**Work on Tickets:**
1. Click "Claim" to assign ticket to yourself
2. Add comments visible to the team
3. Attach files if needed
4. Click "Resolve" when complete
5. Enter resolution notes
6. Points are auto-assigned by category

**Unclaim Tickets:**
- Click "Unclaim" to release assignment if needed

**Via Discord:**
- View ticket details with bot commands
- Add comments through Discord thread
- Resolve directly from Discord

**Restrictions:**
- Cannot bulk operate on tickets
- Cannot reassign to others
- Cannot approve ticket points (Ticketing Admin does this)

---

#### Ticketing Admin

**Getting Started:**
1. Run `/link` in Discord to connect your account
2. Access the ticket dashboard at `/ops/tickets/`

**All Ticketing Support Features Plus:**

**Bulk Operations:**
1. Select multiple tickets using checkboxes
2. Click "Bulk Claim" or "Bulk Resolve"
3. Confirm action

**Reassign Tickets:**
- Change assignee to another support member
- Useful for workload balancing

**Change Ticket Category:**
- Update category if initially misclassified
- Affects point value

**Reopen Resolved Tickets:**
- Click "Reopen" if issue resurfaces
- Adds back to queue

**Batch Approve Ticket Points:**
1. Navigate to Scoring > Review Tickets
2. Review all resolved tickets
3. Verify point values by category
4. Bulk approve for final score aggregation

**Administrative Actions:**
- Create tickets for teams via `/tickets create`
- Cancel tickets via `/tickets cancel`
- Clear all tickets (reset operation)

**View Leaderboard:**
- Navigate to Scoring > Leaderboard

---

#### System Admin

**Getting Started:**
1. Run `/link` in Discord to connect your account
2. Access Django admin at `/admin/`

**All Features Available Plus:**

**Configure Competition:**
- Set start/end times: `/competition set-start-time` and `/competition set-end-time`
- Set registration deadline and capacity
- Configure controlled applications: `/competition set-apps`
- Set max team members: `/competition set-max-members`

**Manage Teams:**
- List teams: `/teams list`
- View team details: `/teams info <team_number>`
- Unlink users: `/teams unlink <users>`
- Reset team: `/teams reset <team_number>`

**Competition Lifecycle:**
- Start competition: `/competition start-competition` (or auto-starts at configured time)
- End competition: `/competition end-competition` (or auto-ends at configured time)
- Broadcast messages: `/competition broadcast <target> <message>`

**Sync with Quotient:**
1. Navigate to Scoring > Configuration
2. View last sync time
3. Trigger manual sync for metadata (boxes, services, injects)

**Export Data:**
1. Navigate to Django admin
2. Select data type (findings, incidents, adjustments, grades, tickets)
3. Export as CSV or JSON
4. Download final aggregated scores

**Manage Student Helpers:**
- Add single helper: `/helpers add @user "Role Name"`
- Import from role: `/helpers import @Role`
- List helpers: `/helpers list`
- Remove helper: `/helpers remove @user`

**Team Packet Distribution:**
1. Navigate to `/team-packets/ops/upload/`
2. Upload packet file (PDF, documents, up to 25MB)
3. Set title and notes
4. Choose distribution methods (email/web)
5. Click "Distribute Now"
6. Monitor delivery at `/team-packets/ops/`

---

### Common Workflows

#### Incident Reporting and Matching Workflow

1. **Blue Team** detects attack and submits incident report
2. **Red Team** documents attack as finding submission
3. **Gold Team** reviews ALL incident reports
4. **Gold Team** matches incidents to red findings based on IP/timing
5. Matched incidents provide point recovery for Blue Team
6. Unmatched red findings result in point penalties for Blue Team

#### Finding Submission and Approval Workflow

1. **Red Team** submits finding after successful attack
2. Finding appears in Gold Team review queue
3. **Gold Team** spot-checks submissions for validity
4. **Gold Team** bulk approves valid findings
5. Approved findings count toward final score adjustments

#### Inject Grading Workflow

1. Teams complete inject tasks in Quotient
2. **White Team** reviews responses and assigns scores
3. Grades submitted to WCComps
4. **Gold Team** spot-checks for consistency
5. **Gold Team** bulk approves grades
6. Approved grades add to final team scores

#### Ticket Resolution Workflow

1. **Blue Team** creates ticket via `/ticket` or web
2. Ticket appears in support dashboard
3. **Ticketing Support** claims ticket
4. Support member works with team to resolve
5. Support member resolves ticket with notes
6. Points auto-assigned by category
7. **Ticketing Admin** batch approves at competition end
8. Approved tickets add to final team scores

---

### Troubleshooting

#### Access Issues

**Problem:** Cannot access web interface
- Check that you ran `/link` in Discord
- Verify Authentik groups assigned correctly
- Confirm OAuth redirect URI matches BASE_URL

**Problem:** Navigation links not appearing
- Verify your Authentik group membership
- Check with admin that groups are configured
- Try logging out and back in

**Problem:** Permission denied on certain pages
- Verify your role has access to that feature
- Check user-roles-and-stories.md for role permissions
- Contact admin if access should be granted

#### Discord Issues

**Problem:** Bot not responding to commands
- Verify bot is online (check Discord server)
- Check bot has proper permissions in channel
- Contact admin to check bot logs

**Problem:** Link command failing
- Verify BASE_URL is configured correctly
- Check Authentik OAuth credentials
- Try `/link` again after a few minutes

#### Ticket Issues

**Problem:** Cannot create ticket
- Verify you're a Blue Team member
- Check ticket category is valid
- Ensure description is not empty

**Problem:** Ticket not appearing in dashboard
- Check DISCORD_TICKET_QUEUE_CHANNEL_ID is set
- Verify ticket was created successfully
- Contact admin to check logs

#### Data Issues

**Problem:** Incident/Finding not appearing
- Allow a few seconds for processing
- Refresh the page
- Check submission was successful (look for confirmation)

**Problem:** Leaderboard not updating
- Leaderboard shows approved items only
- Wait for Gold Team review and approval
- Final aggregation happens at competition end

---

### Getting Help

**General Questions:**
- Contact Gold Team or System Admin
- Create ticket in Discord if urgent

**Technical Issues:**
- Contact System Admin
- Check troubleshooting section above
- Review logs if you have admin access

**Competition Rules:**
- Contact Gold Team for clarification
- Review competition guidelines

**Account/Access Issues:**
- Contact System Admin
- Verify Authentik group membership
- Check that `/link` was completed

---

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
