# Team Onboarding System Testing Plan

This document outlines testing requirements for the team onboarding system as each phase is implemented.

## Phase 1: Core Models (Complete)

### Season Model
- [x] Creation with name and year
- [x] Ordering by year (newest first)
- [x] Unique year constraint
- [x] is_active flag defaults to False

### Event Model
- [x] Creation with required fields (season, name, event_type, date)
- [x] Default values (start_time 09:00, end_time 17:00, max_teams 50)
- [x] Unique constraint on (season, event_type, event_number)
- [x] Ordering by season and date
- [x] registration_open, is_active, is_finalized flags

### RegistrationContact Model
- [x] Creation with registration, role, name, email
- [x] All role types (captain, co_captain, coach, site_judge)
- [x] Unique constraint on (registration, role)
- [x] Phone field optional

### RegistrationEventEnrollment Model
- [x] Creation linking registration to event
- [x] Unique constraint on (registration, event)
- [x] enrolled_at timestamp auto-set

### EventTeamAssignment Model
- [x] Creation linking event, registration, and team
- [x] Unique constraint on (event, registration)
- [x] Unique constraint on (event, team)
- [x] credentials_sent_at and password_generated fields

### TeamRegistration Extensions
- [x] edit_token generated on creation
- [x] edit_token unique across registrations
- [x] edit_token_expires nullable

### Forms
- [x] SchoolInfoForm validation
- [x] CaptainContactForm requires name, email, phone
- [x] CoachContactForm requires name, email; phone optional
- [x] OptionalContactForm all fields optional
- [x] OptionalContactForm.has_data() detection
- [x] EventSelectionForm loads open events from active season
- [x] EventSelectionForm requires at least one event
- [x] RegistrationForm creates captain contact on save

---

## Phase 2: Registration Flow (Pending)

### Season/Event CRUD Views
- [ ] Season list view (Gold Team only)
- [ ] Season create/edit (Gold Team only)
- [ ] Event list view shows enrollment counts
- [ ] Event create with all fields
- [ ] Event edit updates correctly
- [ ] Event delete with confirmation
- [ ] Event detail shows enrolled registrations

### Public Registration Flow
- [ ] Multi-step form navigation (school → captain → coach → optional contacts → events → confirm)
- [ ] Form state preserved between steps
- [ ] Back navigation works
- [ ] Captain email required and validated
- [ ] Coach email required and different from captain
- [ ] Co-captain and site judge optional
- [ ] Event selection shows only open events from active season
- [ ] Confirmation page shows all entered data
- [ ] Submit creates TeamRegistration, contacts, and enrollments
- [ ] Success page shows edit token link

### Token-Based Self-Service Editing
- [ ] Valid token loads registration for editing
- [ ] Expired token shows error
- [ ] Invalid token shows 404
- [ ] Can update contact information
- [ ] Can add/remove event enrollments (if registration not yet approved)
- [ ] Cannot edit after certain status (e.g., credentials_sent)

### Admin Approval Workflow
- [ ] Review list shows pending registrations
- [ ] Review list filters by status
- [ ] Approve action sets status, approved_at, approved_by
- [ ] Reject action requires reason
- [ ] Mark as paid sets status and paid_at
- [ ] Cannot approve already approved registration

### Team Assignment
- [ ] assign_teams_for_event randomly assigns team numbers
- [ ] Only approved+paid registrations get assignments
- [ ] Each team number assigned only once per event
- [ ] Same school gets different team numbers across events
- [ ] Assignment recorded with timestamp
- [ ] Reassignment prevented (or requires explicit override)

---

## Phase 3: Email Service (Pending)

### SendmailBackend
- [ ] Builds valid MIME message
- [ ] Handles plain text body
- [ ] Handles HTML body
- [ ] Handles attachments (PDF)
- [ ] Calls sendmail subprocess correctly
- [ ] Returns success/failure status
- [ ] Handles sendmail errors gracefully

### EmailService
- [ ] send() dispatches to backend
- [ ] send_templated() renders template and sends
- [ ] Templates render with context variables
- [ ] Multiple recipients supported

### Email Types
- [ ] Registration confirmation sent on submit
- [ ] Confirmation includes edit token link
- [ ] Approval notification sent to captain and coach
- [ ] Credentials email includes team number, password, packet attachment
- [ ] Event reminder includes event details and timing

### Integration with Authentik
- [ ] generate_blueteam_password() creates valid password
- [ ] reset_blueteam_password() updates Authentik and enables account
- [ ] Password stored in EventTeamAssignment for re-send

---

## Phase 4: Scoring by Event (Pending)

### Score Model Extensions
- [ ] RedTeamFinding accepts optional event FK
- [ ] OrangeTeamBonus accepts optional event FK
- [ ] InjectGrade accepts optional event FK
- [ ] IncidentReport accepts optional event FK
- [ ] ServiceScore accepts optional event FK

### EventScore Model
- [ ] Created per team per event
- [ ] Links to EventTeamAssignment for traceability
- [ ] Stores component scores (service, inject, orange, red, incident, sla)
- [ ] Calculates total_score
- [ ] Tracks rank within event
- [ ] calculated_at timestamp updates on recalculation

### Score Calculator
- [ ] calculate_team_event_score() scopes to specific event
- [ ] recalculate_event_scores() updates all teams for event
- [ ] Ranking algorithm handles ties correctly
- [ ] Score visible only after event is_finalized

### Leaderboard
- [ ] Requires event parameter
- [ ] Shows only finalized event scores
- [ ] Displays rank, team number, school name (from assignment), scores
- [ ] Hides scores for non-finalized events

### Score Card PDF
- [ ] generate_scorecard_pdf() creates valid PDF
- [ ] PDF includes school name, team number, event details
- [ ] PDF includes score breakdown by category
- [ ] PDF includes rank and total score
- [ ] PDF styling matches branding

### Score Card Distribution
- [ ] send_scorecards_batch() sends to all teams for event
- [ ] send_scorecard_single() re-sends to one team
- [ ] scorecard_sent_at tracked on EventScore
- [ ] Email includes PDF attachment

---

## Phase 5: Packets + Reminders (Pending)

### TeamPacket Extensions
- [ ] Optional event FK
- [ ] Packet can be associated with specific event or general

### Packet Distribution
- [ ] Packet attached to credentials email
- [ ] Web download authenticated by team credentials
- [ ] Download count tracked
- [ ] First download timestamp tracked

### Event Reminders
- [ ] reminder_days JSONField stores configured days
- [ ] Manual reminder trigger from admin UI
- [ ] Reminder email sent to captain and coach
- [ ] last_reminder_sent updated after sending

---

## Integration Tests

### End-to-End Registration Flow
- [ ] Complete registration from start to credentials received
- [ ] Verify all database records created correctly
- [ ] Verify all emails sent at correct points
- [ ] Verify team can log in with credentials

### Multi-Event Scenario
- [ ] School registers for multiple events
- [ ] School gets different team numbers per event
- [ ] Scores tracked separately per event
- [ ] School receives separate score cards per event

### Season Transition
- [ ] New season created
- [ ] Events created for new season
- [ ] Old season registrations preserved
- [ ] New registrations go to active season only

---

## Performance Tests

### Bulk Operations
- [ ] assign_teams_for_event handles 50 teams efficiently
- [ ] send_credentials_batch handles 50 emails without timeout
- [ ] recalculate_event_scores handles 50 teams quickly
- [ ] send_scorecards_batch handles 50 PDFs and emails

### Concurrent Access
- [ ] Multiple simultaneous registrations don't conflict
- [ ] Team assignment doesn't create duplicates under race conditions
- [ ] Score updates don't lose data under concurrent edits

---

## Security Tests

### Authorization
- [ ] Public registration accessible without auth
- [ ] Edit token validates correctly
- [ ] Admin views require Gold Team permission
- [ ] Score entry requires appropriate team permission
- [ ] Team credentials only visible to assigned team

### Input Validation
- [ ] Email fields reject invalid formats
- [ ] Phone fields accept various formats
- [ ] School name length limits enforced
- [ ] Event dates validated (not in past for new events)
- [ ] Rejection reason required and sanitized

### Token Security
- [ ] Edit tokens are cryptographically random
- [ ] Edit tokens cannot be guessed or enumerated
- [ ] Expired tokens rejected
- [ ] Tokens not logged or exposed in URLs inappropriately
