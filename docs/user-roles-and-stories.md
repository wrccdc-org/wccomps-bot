# User Roles and Stories

## Overview

WCComps is a cybersecurity competition management platform that works alongside Quotient (the real-time scoring engine). WCComps handles score adjustments, incident/finding tracking, and administrative functions while Quotient handles live uptime monitoring and service checks.

---

## System Architecture

### Scoring Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    DURING COMPETITION                            │
├────────────────────────────────┬────────────────────────────────┤
│  QUOTIENT (Real-time)          │  WCComps (Collection)          │
│  ─────────────────────         │  ───────────────────────       │
│  • Uptime monitoring           │  • Red findings submitted      │
│  • Service checks              │  • Blue incidents submitted    │
│  • Live scoring display        │  • Orange adjustments          │
│  • Inject problem delivery     │  • Inject grades               │
│  • Inject response collection  │  • Ticket resolutions          │
│                                │  • Gold/Admin spot-checks      │
└────────────────────────────────┴────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    COMPETITION END                               │
├─────────────────────────────────────────────────────────────────┤
│  FINAL SCORE = Quotient Base Score + WCComps Adjustments        │
│                                                                  │
│  Quotient Base:           WCComps Adjustments:                  │
│  • Uptime points          • Red findings approved (Blue -)      │
│  • Service points         • Incident matches (Blue + recovery)  │
│                           • Orange adjustments (+/-)            │
│                           • Inject grades (+)                   │
│                           • Ticket category points (+)          │
└─────────────────────────────────────────────────────────────────┘
```

### Unified Scoring Flow Pattern

All scoring inputs in WCComps follow the same pattern:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   SUBMIT    │ ──► │   REVIEW    │ ──► │   APPROVE   │ ──► │  AGGREGATE  │
│   (Form)    │     │   (Queue)   │     │  (Action)   │     │(End of Comp)│
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

| Type | Submitter | Reviewer | Review Process | Point Impact |
|------|-----------|----------|----------------|--------------|
| **Red Finding** | Red Team | Gold Team | Spot check, bulk approve | Blue Team loses points |
| **Blue Incident** | Blue Team | Gold Team | Review ALL, match to finding | Blue Team recovers points |
| **Orange Adjustment** | Orange Team | Gold Team | Spot check, bulk approve | +/- configurable points |
| **Inject Grade** | White Team | Gold Team | Spot check, bulk approve | + points per inject |
| **Ticket Resolution** | Ticketing Support | Ticketing Admin | Batch approve at end | Fixed points per category |

---

## User Roles

### Blue Team (Competition Participants)

**Identity**: Members of `WCComps_BlueTeam{N}` Authentik groups (e.g., `WCComps_BlueTeam01`)

Blue Team members are competition participants defending their assigned network infrastructure.

**Permissions**:
- Submit incident reports for their team
- View their team's incident reports
- Create and manage support tickets
- View and download team packets

**Restrictions**:
- Cannot view leaderboard (use Quotient during competition)
- Cannot view other teams' data

---

### Red Team (Attackers)

**Identity**: Members of `WCComps_RedTeam` Authentik group

Red Team members simulate adversaries attacking Blue Team infrastructure.

**Permissions**:
- Submit red team findings (attack reports)
- View ALL red team findings (all members' submissions for coordination)

**Restrictions**:
- Cannot view leaderboard
- Cannot see if findings were matched to incidents
- Cannot see approval status of findings

---

### Gold Team (Competition Organizers/Judges)

**Identity**: Members of `WCComps_GoldTeam` Authentik group

Gold Team members verify incidents, review findings, and ensure fair competition.

**Permissions**:
- View leaderboard
- Review and match ALL incident reports to red findings
- Spot-check and bulk approve red team findings
- Spot-check and bulk approve orange team adjustments
- Spot-check and bulk approve inject grades
- View team mappings
- Manage school information

**Restrictions**:
- Cannot submit orange adjustments (can only review)
- Cannot submit inject grades (can only review)

---

### White Team (Inject Graders)

**Identity**: Members of `WCComps_WhiteTeam` Authentik group

White Team members grade scenario-based inject submissions. Inject problems and responses are handled in Quotient; grades are submitted to WCComps.

**Permissions**:
- View leaderboard
- Submit inject grades (per-inject, per-team)
- View inject submission details (synced from Quotient)

**Restrictions**:
- Cannot review incidents or red team findings
- Cannot submit orange adjustments

---

### Orange Team (Bonus/Penalty Adjustments)

**Identity**: Members of `WCComps_OrangeTeam` Authentik group

Orange Team awards bonus points or penalties for behavior, task completion, or rule violations.

**Permissions**:
- Submit point adjustments with dynamic check types
- View their own submitted adjustments

**Check Types** (dynamic, user-defined):
- Customer service call answered
- Network diagram completed
- Password reset assistance
- Rule violation (negative)
- Professional behavior bonus
- *(New types created on first use, available for future entries)*

**Restrictions**:
- Cannot approve their own adjustments (Gold Team reviews)
- Cannot view leaderboard

---

### Ticketing Support

**Identity**: Members of `WCComps_Ticketing_Support` Authentik group

Support staff handle participant support tickets during competition.

**Permissions**:
- View all tickets (list and detail)
- Claim tickets (assign to self)
- Unclaim tickets (release assignment)
- Resolve tickets (category determines point value)
- Add comments and attachments to tickets

**Restrictions**:
- Cannot view leaderboard
- Cannot perform bulk operations
- Cannot reassign to others
- Cannot approve ticket points (Ticketing Admin does batch approval)

---

### Ticketing Admin

**Identity**: Members of `WCComps_Ticketing_Admin` Authentik group

Ticket administrators have elevated permissions for ticket management.

**Permissions**:
- All Ticketing Support permissions
- View leaderboard
- Bulk claim/resolve multiple tickets
- Reassign tickets to other users
- Change ticket category
- Reopen resolved tickets
- Batch approve ticket points at competition end
- Clear all tickets (administrative reset)

---

### System Admin

**Identity**: Members of `WCComps_Discord_Admin` Authentik group with `is_staff` flag

System administrators have full access to system configuration.

**Permissions**:
- All Gold Team permissions
- All Ticketing Admin permissions
- Django admin access
- Competition configuration (timing, parameters)
- Sync operations with Quotient
- Score recalculation
- Data export (CSV/JSON)
- Team registration management

---

## Role-Feature Matrix

| Feature | Blue | Red | Gold | White | Orange | Ticket Supp | Ticket Admin | Admin |
|---------|------|-----|------|-------|--------|-------------|--------------|-------|
| View Leaderboard | | | ✓ | ✓ | | | ✓ | ✓ |
| Submit Incident | ✓ | | | | | | | ✓ |
| View Own Incidents | ✓ | | ✓ | | | | | ✓ |
| Submit Red Finding | | ✓ | | | | | | ✓ |
| View All Red Findings | | ✓ | ✓ | | | | | ✓ |
| Review/Match Incidents | | | ✓ | | | | | ✓ |
| Approve Red Findings | | | ✓ | | | | | ✓ |
| Submit Inject Grade | | | | ✓ | | | | ✓ |
| Approve Inject Grades | | | ✓ | | | | | ✓ |
| Submit Orange Adjustment | | | | | ✓ | | | ✓ |
| Approve Orange Adjust | | | ✓ | | | | | ✓ |
| View Team Mappings | | | ✓ | | | | | ✓ |
| Manage School Info | | | ✓ | | | | | ✓ |
| Create Tickets | ✓ | | | | | | | |
| View All Tickets | | | | | | ✓ | ✓ | ✓ |
| Claim/Resolve Tickets | | | | | | ✓ | ✓ | ✓ |
| Bulk Ticket Operations | | | | | | | ✓ | ✓ |
| Approve Ticket Points | | | | | | | ✓ | ✓ |
| View Team Packets | ✓ | | | | | | | ✓ |
| Export Data | | | | | | | | ✓ |
| Django Admin | | | | | | | | ✓ |

---

## User Stories

### Registration Stories (Pre-Competition)

#### REG-1: Register Team for Competition
> As a **coach or team captain**, I want to **register my team for the competition** so that I can **secure a spot and receive account credentials**.

**Acceptance Criteria**:
- Registration form captures school name, contact email, phone
- Check for registration deadline (reject if past)
- Check for capacity limit (reject if full)
- Confirmation shown with next steps
- Admin notified of new registration

#### REG-2: Review Team Registration
> As a **System Admin**, I want to **review and approve team registrations** so that I can **verify eligibility and manage capacity**.

**Acceptance Criteria**:
- List of pending registrations
- View registration details
- Approve or reject with reason
- Approved teams receive invoice information
- After payment confirmed, account credentials emailed

#### REG-3: Track Registration Status
> As a **registrant**, I want to **check my registration status** so that I can **know if I'm approved and what's next**.

**Acceptance Criteria**:
- Status page showing: Pending → Approved → Paid → Credentials Sent
- Contact information if questions

---

### Blue Team Stories

#### BT-1: Report Security Incident
> As a **Blue Team member**, I want to **submit an incident report** so that I can **document attacks I've detected and recover points**.

**Acceptance Criteria**:
- Form captures: target box, source IP, services affected, attack type, description
- Box selection auto-populates destination IP and available services
- Can only submit for my team's infrastructure
- Confirmation shown after submission

#### BT-2: View My Incidents
> As a **Blue Team member**, I want to **view my team's incident reports** so that I can **see what we've submitted and avoid duplicates**.

**Acceptance Criteria**:
- List of all incidents submitted by my team
- Shows submission time, box, attack type
- Detail view for each incident
- Status NOT shown (Blue doesn't see match status)

#### BT-3: Request Support
> As a **Blue Team member**, I want to **create a support ticket** so that I can **get help with technical issues**.

**Acceptance Criteria**:
- Ticket creation with category selection
- File attachment support
- View ticket status and staff responses
- Can cancel own unresolved tickets

#### BT-4: Download Team Packets
> As a **Blue Team member**, I want to **download team packets** so that I can **access competition materials**.

**Acceptance Criteria**:
- List of available packets for my team
- Secure download links
- Shows upload date and description

---

### Red Team Stories

#### RT-1: Document Attack
> As a **Red Team member**, I want to **submit a finding** so that I can **document successful attacks**.

**Acceptance Criteria**:
- Form captures: target team, target box, source IP, attack type, description
- Box selection auto-populates destination IP and services
- Attack type autocomplete from previous submissions (XSS-safe)
- Confirmation shown after submission

#### RT-2: View All Findings
> As a **Red Team member**, I want to **view all red team findings** so that I can **coordinate with other red team members and avoid duplicates**.

**Acceptance Criteria**:
- List of ALL findings from ALL red team members
- Filter by team targeted, attack type, submitter
- Shows submission time, target, attack type
- Approval status NOT shown

---

### Gold Team Stories

#### GT-1: View Leaderboard
> As a **Gold Team member**, I want to **view the leaderboard** so that I can **monitor competition standings**.

**Acceptance Criteria**:
- Leaderboard displays all teams with rankings
- Shows current aggregated score
- Shows score breakdown by category

#### GT-2: Review and Match Incidents
> As a **Gold Team member**, I want to **review ALL incident reports and match them to red findings** so that I can **verify defensive detections**.

**Acceptance Criteria**:
- Queue of ALL incident reports (must review each one)
- View incident details
- See suggested red finding matches (by source IP, timing)
- Match incident to specific red finding
- Reject incident if invalid
- Track review progress

#### GT-3: Spot-Check Red Findings
> As a **Gold Team member**, I want to **spot-check red team findings** so that I can **verify data looks correct before bulk approval**.

**Acceptance Criteria**:
- List of pending red findings
- Quick scan view (team, attack type, timestamp)
- Flag suspicious entries for detailed review
- Bulk approve all unflagged entries

#### GT-4: Review Orange Adjustments
> As a **Gold Team member**, I want to **review orange team adjustments** so that I can **approve or reject point changes**.

**Acceptance Criteria**:
- List of pending adjustments
- Shows team, check type, point value (+/-), reason, submitter
- Approve or reject each (or bulk approve)
- Rejected items notify Orange Team submitter

#### GT-5: Review Inject Grades
> As a **Gold Team member**, I want to **spot-check inject grades** so that I can **verify grading consistency**.

**Acceptance Criteria**:
- List of submitted grades by inject and team
- Spot-check for outliers or suspicious values
- Bulk approve when satisfied

#### GT-6: Monitor Team Mappings
> As a **Gold Team member**, I want to **view team mappings** so that I can **see participant assignments**.

**Acceptance Criteria**:
- List all teams with member count
- Show Discord/Authentik usernames
- Search/filter by team number or name

#### GT-7: Manage School Information
> As a **Gold Team member**, I want to **manage school contact information** so that I can **communicate with coaches**.

**Acceptance Criteria**:
- View/edit school name, contact emails per team
- Import from CSV
- Track last updated

---

### White Team Stories

#### WT-1: Submit Inject Grades
> As a **White Team member**, I want to **submit grades for inject responses** so that I can **score teams on business tasks**.

**Acceptance Criteria**:
- List of injects with grading status
- Select inject, select team
- Enter score (and optionally max points)
- Track grading progress (X of Y teams graded)

#### WT-2: View Leaderboard
> As a **White Team member**, I want to **view the leaderboard** so that I can **see standings**.

**Acceptance Criteria**:
- Access to leaderboard
- Can see overall rankings

---

### Orange Team Stories

#### OT-1: Submit Point Adjustment
> As an **Orange Team member**, I want to **submit a point adjustment** so that I can **recognize performance or penalize violations**.

**Acceptance Criteria**:
- Select team
- Select or create check type (dynamic list)
- Enter point value (positive or negative)
- Provide reason/justification
- Submission goes to Gold Team for review
- View my submitted adjustments and their status

---

### Ticketing Stories

#### TS-1: View Ticket Queue
> As a **Ticketing Support member**, I want to **view all tickets** so that I can **identify issues needing attention**.

**Acceptance Criteria**:
- List with status filter (open, claimed, resolved, cancelled)
- Sort by age, team, category, assignee
- Search by ticket number, title, description
- Stale ticket indicators

#### TS-2: Work Ticket
> As a **Ticketing Support member**, I want to **claim and resolve tickets** so that I can **help participants**.

**Acceptance Criteria**:
- Claim ticket (assigns to me)
- Add comments visible to participant
- Add attachments
- Unclaim if needed
- Resolve (points auto-assigned by category)

#### TA-1: Bulk Operations
> As a **Ticketing Admin**, I want to **perform bulk operations** so that I can **efficiently manage high volumes**.

**Acceptance Criteria**:
- Select multiple tickets
- Bulk claim or resolve
- Confirmation of results

#### TA-2: Approve Ticket Points
> As a **Ticketing Admin**, I want to **batch approve ticket points at competition end** so that I can **finalize ticket scoring**.

**Acceptance Criteria**:
- View all resolved tickets with point values
- Verify points by category are correct
- Bulk approve for final aggregation

---

### Admin Stories

#### AD-1: Configure Competition
> As a **System Admin**, I want to **configure competition settings** so that I can **control timing and parameters**.

**Acceptance Criteria**:
- Set competition start/end times
- Set registration deadline and capacity
- Configure controlled applications (Authentik)
- Set max team members

#### AD-2: Sync with Quotient
> As a **System Admin**, I want to **sync data with Quotient** so that I can **ensure consistency**.

**Acceptance Criteria**:
- Sync metadata (boxes, services, injects)
- View last sync time
- Manual sync trigger

#### AD-3: Export Data
> As a **System Admin**, I want to **export all scoring data** so that I can **analyze and archive competition results**.

**Acceptance Criteria**:
- Export red findings (CSV/JSON)
- Export incidents (CSV/JSON)
- Export orange adjustments (CSV/JSON)
- Export inject grades (CSV/JSON)
- Export ticket resolutions (CSV/JSON)
- Export final aggregated scores

#### AD-4: Aggregate Final Scores
> As a **System Admin**, I want to **trigger final score aggregation** so that I can **produce competition results**.

**Acceptance Criteria**:
- Verify all reviews complete (incidents matched, approvals done)
- Trigger aggregation
- Combine Quotient base + WCComps adjustments
- Generate final leaderboard

---

### Team Packet Stories

#### TP-1: Upload Packets
> As a **System Admin**, I want to **upload packets for teams** so that I can **distribute competition materials**.

**Acceptance Criteria**:
- Upload file with description
- Assign to specific team or all teams
- Track upload date

#### TP-2: Download Packets
> As a **Blue Team member**, I want to **download my team's packets** so that I can **access materials**.

**Acceptance Criteria**:
- List packets available to my team
- Secure download
- Cannot access other teams' packets

---

### Discord Integration Stories

#### DI-1: Link Discord Account
> As a **participant**, I want to **link my Discord account** so that I can **use Discord bot features**.

**Acceptance Criteria**:
- Initiate from Discord bot command
- OAuth flow to authenticate
- Confirmation of link
- Can unlink/relink

#### DI-2: Receive Ticket Notifications
> As a **Blue Team member**, I want to **receive Discord notifications** so that I can **respond to ticket updates**.

**Acceptance Criteria**:
- Notification when claimed, commented, resolved
- Direct message or team channel

#### DI-3: Manage Tickets via Discord
> As a **Ticketing Support**, I want to **manage tickets via Discord** so that I can **work without switching to web**.

**Acceptance Criteria**:
- View ticket details via command
- Claim/resolve via command
- Add comments via command

---

### Competition Lifecycle Stories

#### CL-1: Pre-Competition Setup
> As a **System Admin**, I want to **set up the competition** so that I can **prepare before participants arrive**.

**Acceptance Criteria**:
- Import team/school info
- Sync metadata from Quotient
- Verify Authentik groups
- Test integrations

#### CL-2: Start Competition
> As a **System Admin**, I want to **start the competition** so that I can **enable participant access**.

**Acceptance Criteria**:
- Manual start via Discord bot
- Participants gain remote access and Quotient access

#### CL-3: End Competition
> As a **System Admin**, I want to **end the competition** so that I can **freeze submissions**.

**Acceptance Criteria**:
- Manual end via Discord bot
- Remote access and Quotient access disabled
- Reviews continue in web UI after competition ends

#### CL-4: Publish Results
> As a **System Admin**, I want to **publish final results** so that I can **share outcomes**.

**Acceptance Criteria**:
- Generate final standings
- Export results
- Optionally reveal to participants

---

## Navigation Requirements

### Primary Navigation (Header)

| Link | Condition | Destination |
|------|-----------|-------------|
| Tickets | `is_ticketing_support` or `is_ticketing_admin` | `/ops/tickets/` |
| Incidents | `is_blue_team` or `is_admin` | `/scoring/incident/submit/` |
| Red Team Findings | `is_red_team` or `is_admin` | `/scoring/red-team/submit/` |
| Scoring | `is_gold_team` or `is_white_team` or `is_ticketing_admin` or `is_admin` | `/scoring/` |
| Team Mappings | `is_gold_team` or `is_admin` | `/ops/group-role-mappings/` |
| School Info | `is_gold_team` or `is_admin` | `/ops/school-info/` |
| Admin | `is_staff` | `/admin/` |

### Scoring Sub-Navigation

| Link | Condition |
|------|-----------|
| Leaderboard | Always (if can access scoring) |
| Review Red Team | `is_gold_team` or `is_admin` |
| Review Incidents | `is_gold_team` or `is_admin` |
| Orange Team | `is_gold_team` or `is_orange_team` or `is_admin` |
| Inject Grading | `is_white_team` or `is_admin` |
| Review Tickets | `is_ticketing_admin` or `is_admin` |
| Configuration | `is_staff` |

---

## Authentik Group Summary

| Group Name | Role |
|------------|------|
| `WCComps_BlueTeam{N}` | Blue Team (N = 01-99) |
| `WCComps_RedTeam` | Red Team |
| `WCComps_GoldTeam` | Gold Team |
| `WCComps_WhiteTeam` | White Team |
| `WCComps_OrangeTeam` | Orange Team |
| `WCComps_Ticketing_Support` | Ticketing Support |
| `WCComps_Ticketing_Admin` | Ticketing Admin |
| `WCComps_Discord_Admin` | System Admin (+ is_staff) |

---

## Data Export Requirements

All primary data inputs must be exportable as CSV and JSON:

| Data Type | Fields | Access |
|-----------|--------|--------|
| Red Findings | team, box, source_ip, attack_type, description, submitter, timestamp, approved | Admin |
| Blue Incidents | team, box, source_ip, attack_type, description, submitter, timestamp, matched_finding | Admin |
| Orange Adjustments | team, check_type, points, reason, submitter, timestamp, approved | Admin |
| Inject Grades | team, inject, score, max_points (optional), grader, timestamp, approved | Admin |
| Ticket Resolutions | ticket_id, team, category, points, resolver, timestamp | Admin |
| Final Scores | team, quotient_base, red_penalty, incident_recovery, orange_adj, inject_points, ticket_points, total | Admin |

---

## Known Issues to Fix

### Permission Issues
- [ ] Leaderboard visible to Blue/Red Team (should be restricted)
- [ ] Nav shows links users can't access
- [ ] Pages accessible by URL to unauthorized users

### UI Inconsistencies
- [ ] Navigation varies across pages
- [ ] Form layouts inconsistent
- [ ] Review queues need similar structure

### Missing Features
- [ ] Team registration flow
- [ ] Orange Team check type management (dynamic)
- [ ] White Team inject grading UI
- [ ] Data export functionality
- [ ] Batch approval workflows

---

## Resolved Decisions

| Question | Answer |
|----------|--------|
| Inject grading scale | Points vary per inject; White Team enters score AND optionally max points |
| Email notifications | WCComps sends emails (SMTP) for: packets, passwords, registration/payment info |
| Data retention | Admin-triggered archive + delete from live system; past results not viewable after archive |
| Ticket category points | Hardcoded per category (see table below) |
| Incident↔Finding matching | Primarily one-to-one; allow flexibility for edge cases |
| Rejected items | Just skipped (stays in system, not matched/approved) |
| In-person competition | Authentik-only auth; Discord features disabled |

---

## Ticket Category Point Values

| Category | Points | Notes |
|----------|--------|-------|
| Service Scoring Validation | 0 | Free verification |
| Box Reset/Scrub | 60 | Fixed |
| Scoring Service Check | 10 | Fixed |
| Black Team Phone Consultation | 100 | Fixed |
| Black Team Hands-on Consultation | 200 | Up to 300 for consultations >45 min |
| Other/General Issue | 0 | Points manually adjusted if needed |
