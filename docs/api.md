# WCComps API Documentation

This document describes the API endpoints available in the WCComps scoring system.

## Authentication

All API endpoints require authentication via Django session cookies. Users must be logged in through the Authentik OAuth flow before accessing these endpoints.

API endpoints use role-based access control (RBAC):
- Public API endpoints: Available to any authenticated user
- Admin-only endpoints: Require Django staff (`is_staff=True`) permissions

## API Endpoints

### Public Scoring API

These endpoints are available to any authenticated user and provide read-only access to scoring data.

#### GET /scoring/api/scores/

Returns current leaderboard scores for all teams.

**Authentication:** Required (any authenticated user)

**Response Format:** JSON

**Response Structure:**
```json
{
  "scores": [
    {
      "rank": 1,
      "team": "Team Alpha",
      "team_number": 1,
      "total": 1234.56,
      "services": 800.00,
      "injects": 200.00,
      "orange": 50.00,
      "red": -100.00,
      "incidents": 150.00,
      "sla": -50.00
    }
  ]
}
```

**Response Fields:**
- `rank`: Team's position on leaderboard
- `team`: Team name
- `team_number`: Team number identifier
- `total`: Total score (sum of all components)
- `services`: Points from service uptime checks
- `injects`: Points from inject grading
- `orange`: Bonus points from Orange Team
- `red`: Point deductions from Red Team findings
- `incidents`: Points recovered through incident reporting
- `sla`: SLA penalty points

**Example:**
```bash
curl -X GET https://wccomps.org/scoring/api/scores/ \
  -H "Cookie: sessionid=YOUR_SESSION_ID"
```

---

#### GET /scoring/api/team/{team_number}/

Returns detailed scoring breakdown for a specific team.

**Authentication:** Required (any authenticated user)

**URL Parameters:**
- `team_number` (integer): Team number (e.g., 1, 2, 3)

**Response Format:** JSON

**Response Structure:**
```json
{
  "team": "Team Alpha",
  "team_number": 1,
  "scores": {
    "total_score": 1234.56,
    "service_points": 800.00,
    "inject_points": 200.00,
    "orange_points": 50.00,
    "red_deductions": -100.00,
    "incident_recovery_points": 150.00,
    "sla_penalties": -50.00,
    "black_adjustments": 0.00
  }
}
```

**Example:**
```bash
curl -X GET https://wccomps.org/scoring/api/team/1/ \
  -H "Cookie: sessionid=YOUR_SESSION_ID"
```

**Error Responses:**
- 404 Not Found: Team with specified number does not exist

---

#### GET /scoring/api/attack-types/

Returns list of attack type suggestions based on previously submitted Red Team findings.

**Authentication:** Required (any authenticated user)

**Response Format:** JSON

**Response Structure:**
```json
{
  "suggestions": [
    "SQL Injection",
    "Cross-Site Scripting",
    "Remote Code Execution",
    "Privilege Escalation"
  ]
}
```

**Notes:**
- Returns up to 50 unique attack types
- Attack types are truncated to 50 characters max
- Results are sorted alphabetically

**Example:**
```bash
curl -X GET https://wccomps.org/scoring/api/attack-types/ \
  -H "Cookie: sessionid=YOUR_SESSION_ID"
```

---

## Export Endpoints (Admin Only)

These endpoints allow administrators to export competition data in CSV or JSON format. All export endpoints require staff permissions (`is_staff=True`).

### Authentication

All export endpoints use Django's `@user_passes_test(lambda u: u.is_staff)` decorator, requiring the user to have staff privileges.

### Export Index

#### GET /scoring/export/

Landing page listing all available export endpoints.

**Authentication:** Admin only (`is_staff=True`)

**Response:** HTML page with links to export endpoints

---

### Red Team Findings Export

#### GET /scoring/export/red-findings/?format={csv|json}

Export all Red Team findings.

**Authentication:** Admin only (`is_staff=True`)

**Query Parameters:**
- `format` (optional): Export format - `csv` or `json` (default: `csv`)

**Response Format:** CSV or JSON

**CSV Columns:**
- ID
- Attack Vector
- Source IP
- Destination IP Template
- Affected Box
- Affected Service
- Affected Teams
- Points Per Team
- Universally Attempted
- Persistence Established
- Approved
- Approved By
- Approved At
- Submitted By
- Created At

**JSON Structure:**
```json
{
  "red_findings": [
    {
      "id": 1,
      "attack_vector": "SQL Injection on login page",
      "source_ip": "10.0.1.100",
      "destination_ip_template": "10.{TEAM}.2.10",
      "affected_box": "web-server",
      "affected_service": "HTTP",
      "affected_teams": ["Team Alpha", "Team Beta"],
      "points_per_team": "50.00",
      "universally_attempted": false,
      "persistence_established": true,
      "is_approved": true,
      "approved_by": "gold_admin",
      "approved_at": "2025-11-28T10:30:00Z",
      "submitted_by": "red_member",
      "created_at": "2025-11-28T10:00:00Z"
    }
  ]
}
```

**Example:**
```bash
# Export as CSV
curl -X GET https://wccomps.org/scoring/export/red-findings/?format=csv \
  -H "Cookie: sessionid=YOUR_SESSION_ID" \
  -O red_findings.csv

# Export as JSON
curl -X GET https://wccomps.org/scoring/export/red-findings/?format=json \
  -H "Cookie: sessionid=YOUR_SESSION_ID" \
  -O red_findings.json
```

---

### Incident Reports Export

#### GET /scoring/export/incidents/?format={csv|json}

Export all Blue Team incident reports.

**Authentication:** Admin only (`is_staff=True`)

**Query Parameters:**
- `format` (optional): Export format - `csv` or `json` (default: `csv`)

**Response Format:** CSV or JSON

**CSV Columns:**
- ID
- Team
- Attack Description
- Source IP
- Destination IP
- Affected Box
- Affected Service
- Attack Detected At
- Attack Mitigated
- Points Returned
- Reviewed
- Matched Finding ID
- Reviewed By
- Reviewed At
- Submitted By
- Created At

**JSON Structure:**
```json
{
  "incidents": [
    {
      "id": 1,
      "team": "Team Alpha",
      "team_number": 1,
      "attack_description": "Detected SQL injection attempt on login form",
      "source_ip": "10.0.1.100",
      "destination_ip": "10.1.2.10",
      "affected_box": "web-server",
      "affected_service": "HTTP",
      "attack_detected_at": "2025-11-28T10:15:00Z",
      "attack_mitigated": true,
      "points_returned": "25.00",
      "gold_team_reviewed": true,
      "matched_to_red_finding_id": 1,
      "reviewed_by": "gold_admin",
      "reviewed_at": "2025-11-28T10:35:00Z",
      "submitted_by": "team1_member",
      "created_at": "2025-11-28T10:20:00Z"
    }
  ]
}
```

**Example:**
```bash
# Export as CSV
curl -X GET https://wccomps.org/scoring/export/incidents/?format=csv \
  -H "Cookie: sessionid=YOUR_SESSION_ID" \
  -O incidents.csv

# Export as JSON
curl -X GET https://wccomps.org/scoring/export/incidents/?format=json \
  -H "Cookie: sessionid=YOUR_SESSION_ID" \
  -O incidents.json
```

---

### Orange Team Adjustments Export

#### GET /scoring/export/orange-adjustments/?format={csv|json}

Export all Orange Team bonus point adjustments.

**Authentication:** Admin only (`is_staff=True`)

**Query Parameters:**
- `format` (optional): Export format - `csv` or `json` (default: `csv`)

**Response Format:** CSV or JSON

**CSV Columns:**
- ID
- Team
- Check Type
- Description
- Points
- Approved
- Approved By
- Approved At
- Submitted By
- Created At

**JSON Structure:**
```json
{
  "orange_adjustments": [
    {
      "id": 1,
      "team": "Team Alpha",
      "team_number": 1,
      "check_type": "Security Hardening",
      "description": "Implemented firewall rules and access controls",
      "points_awarded": "100.00",
      "is_approved": true,
      "approved_by": "gold_admin",
      "approved_at": "2025-11-28T11:00:00Z",
      "submitted_by": "orange_member",
      "created_at": "2025-11-28T10:45:00Z"
    }
  ]
}
```

**Example:**
```bash
# Export as CSV
curl -X GET https://wccomps.org/scoring/export/orange-adjustments/?format=csv \
  -H "Cookie: sessionid=YOUR_SESSION_ID" \
  -O orange_adjustments.csv

# Export as JSON
curl -X GET https://wccomps.org/scoring/export/orange-adjustments/?format=json \
  -H "Cookie: sessionid=YOUR_SESSION_ID" \
  -O orange_adjustments.json
```

---

### Inject Grades Export

#### GET /scoring/export/inject-grades/?format={csv|json}

Export all inject grading data.

**Authentication:** Admin only (`is_staff=True`)

**Query Parameters:**
- `format` (optional): Export format - `csv` or `json` (default: `csv`)

**Response Format:** CSV or JSON

**CSV Columns:**
- Team
- Team Number
- Inject ID
- Inject Name
- Max Points
- Points Awarded
- Approved
- Approved By
- Approved At
- Graded By
- Graded At

**JSON Structure:**
```json
{
  "inject_grades": [
    {
      "team": "Team Alpha",
      "team_number": 1,
      "inject_id": "inject-001",
      "inject_name": "Network Diagram",
      "max_points": "100.00",
      "points_awarded": "85.00",
      "is_approved": true,
      "approved_by": "gold_admin",
      "approved_at": "2025-11-28T12:00:00Z",
      "graded_by": "white_grader",
      "graded_at": "2025-11-28T11:45:00Z"
    }
  ]
}
```

**Example:**
```bash
# Export as CSV
curl -X GET https://wccomps.org/scoring/export/inject-grades/?format=csv \
  -H "Cookie: sessionid=YOUR_SESSION_ID" \
  -O inject_grades.csv

# Export as JSON
curl -X GET https://wccomps.org/scoring/export/inject-grades/?format=json \
  -H "Cookie: sessionid=YOUR_SESSION_ID" \
  -O inject_grades.json
```

---

### Final Scores Export

#### GET /scoring/export/final-scores/?format={csv|json}

Export final calculated scores with complete breakdown for all teams.

**Authentication:** Admin only (`is_staff=True`)

**Query Parameters:**
- `format` (optional): Export format - `csv` or `json` (default: `csv`)

**Response Format:** CSV or JSON

**CSV Columns:**
- Rank
- Team
- Team Number
- Total Score
- Service Points
- Inject Points
- Orange Points
- Red Deductions
- Incident Recovery Points
- SLA Penalties
- Black Adjustments
- Calculated At

**JSON Structure:**
```json
{
  "final_scores": [
    {
      "rank": 1,
      "team": "Team Alpha",
      "team_number": 1,
      "total_score": "1234.56",
      "service_points": "800.00",
      "inject_points": "200.00",
      "orange_points": "50.00",
      "red_deductions": "-100.00",
      "incident_recovery_points": "150.00",
      "sla_penalties": "-50.00",
      "black_adjustments": "0.00",
      "calculated_at": "2025-11-28T12:00:00Z"
    }
  ]
}
```

**Example:**
```bash
# Export as CSV
curl -X GET https://wccomps.org/scoring/export/final-scores/?format=csv \
  -H "Cookie: sessionid=YOUR_SESSION_ID" \
  -O final_scores.csv

# Export as JSON
curl -X GET https://wccomps.org/scoring/export/final-scores/?format=json \
  -H "Cookie: sessionid=YOUR_SESSION_ID" \
  -O final_scores.json
```

---

## Error Handling

All API endpoints return standard HTTP status codes:

- `200 OK`: Request successful
- `400 Bad Request`: Invalid request parameters
- `401 Unauthorized`: Authentication required
- `403 Forbidden`: Insufficient permissions
- `404 Not Found`: Resource not found
- `405 Method Not Allowed`: Invalid HTTP method
- `500 Internal Server Error`: Server error

Error responses include a JSON body with error details:
```json
{
  "error": "Error message description"
}
```

## Rate Limiting

Currently, no rate limiting is enforced on API endpoints. This may be subject to change in future versions.

## CORS Policy

Cross-Origin Resource Sharing (CORS) is not enabled. All API requests must originate from the same domain as the application.

## Data Formats

### Timestamps

All timestamps are returned in ISO 8601 format with UTC timezone:
```
2025-11-28T10:30:00Z
```

### Decimal Numbers

Numeric fields (points, scores) are returned as:
- JSON: Strings to preserve decimal precision (e.g., `"1234.56"`)
- CSV: Numeric values as-is

## Notes

- The application does not provide a REST API for creating, updating, or deleting resources. All data modifications must be done through the web interface.
- Export endpoints return file downloads with appropriate `Content-Disposition` headers.
- API endpoints rely on Django session authentication. API clients must maintain session cookies.
- For programmatic access, consider using the export endpoints to retrieve bulk data rather than polling the real-time API endpoints.
