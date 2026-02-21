"""Integration tests for scoring workflows.

Tests cover the complete end-to-end flows for:
1. Incident Report workflow (Blue Team -> Gold Team review)
2. Red Team Finding workflow (Red Team -> Gold Team approval)
3. Orange Adjustment workflow (Orange Team -> Gold Team approval)
4. Inject Grade workflow (White Team -> Gold Team approval)

These tests verify data integrity and workflow state transitions at the model level,
ensuring that approval tracking and point calculations work correctly throughout
each workflow.
"""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from scoring.models import (
    IncidentReport,
    InjectScore,
    OrangeCheckType,
    OrangeTeamScore,
    RedTeamFinding,
)
from team.models import Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup_teams():
    """Create test teams."""
    team1 = Team.objects.create(
        team_name="Blue Team 1",
        team_number=1,
        max_members=10,
    )
    team2 = Team.objects.create(
        team_name="Blue Team 2",
        team_number=2,
        max_members=10,
    )
    return team1, team2


@pytest.fixture
def setup_users():
    """Create test users."""
    blue1_user = User.objects.create_user(username="blue1_user", password="test123")
    blue2_user = User.objects.create_user(username="blue2_user", password="test123")
    red_user = User.objects.create_user(username="red_user", password="test123")
    orange_user = User.objects.create_user(username="orange_user", password="test123")
    white_user = User.objects.create_user(username="white_user", password="test123")
    gold_user = User.objects.create_user(username="gold_user", password="test123")

    return {
        "blue1": blue1_user,
        "blue2": blue2_user,
        "red": red_user,
        "orange": orange_user,
        "white": white_user,
        "gold": gold_user,
    }


class TestIncidentWorkflow:
    """Test complete incident report workflow from Blue Team submission to Gold Team review."""

    def test_step1_blue_team_submits_incident(self, setup_teams, setup_users):
        """Step 1: Blue Team submits incident - verify initial state."""
        team1, team2 = setup_teams
        users = setup_users

        incident = IncidentReport.objects.create(
            team=team1,
            submitted_by=users["blue1"],
            attack_description="SQL injection detected on web server",
            source_ip="192.168.1.100",
            destination_ip="10.100.11.22",
            affected_boxes=["Web Server"],
            affected_service="HTTP",
            attack_detected_at=timezone.now(),
            attack_mitigated=True,
            evidence_notes="Firewall logs show repeated SQL injection attempts",
        )

        # Verify initial workflow state
        assert incident.team == team1
        assert incident.submitted_by == users["blue1"]
        assert incident.gold_team_reviewed is False
        assert incident.matched_to_red_finding is None
        assert incident.points_returned == Decimal("0")
        assert incident.reviewed_by is None
        assert incident.reviewed_at is None

    def test_step2_incident_appears_in_review_queue(self, setup_teams, setup_users):
        """Step 2: Incident appears in Gold Team review queue."""
        team1, team2 = setup_teams
        users = setup_users

        # Create unreviewed incident
        incident = IncidentReport.objects.create(
            team=team1,
            submitted_by=users["blue1"],
            attack_description="Port scan detected",
            source_ip="192.168.1.50",
            destination_ip="10.100.11.25",
            affected_boxes=["Database Server"],
            affected_service="PostgreSQL",
            attack_detected_at=timezone.now(),
            attack_mitigated=True,
            gold_team_reviewed=False,
        )

        # Verify incident is in review queue
        unreviewed_incidents = IncidentReport.objects.filter(gold_team_reviewed=False)
        assert incident in unreviewed_incidents
        assert unreviewed_incidents.count() == 1

    def test_step3_gold_team_matches_incident_to_finding(self, setup_teams, setup_users):
        """Step 3: Gold Team matches incident to Red Team finding and awards points."""
        team1, team2 = setup_teams
        users = setup_users

        # Create approved Red Team finding
        red_finding = RedTeamFinding.objects.create(
            submitted_by=users["red"],
            attack_vector="Port scanning campaign",
            source_ip="192.168.1.50",
            affected_boxes=["Database Server"],
            affected_service="PostgreSQL",
            universally_attempted=True,
            persistence_established=False,
            points_per_team=Decimal("50.00"),
            is_approved=True,
            approved_by=users["gold"],
            approved_at=timezone.now(),
        )
        red_finding.affected_teams.add(team1, team2)

        # Create incident
        incident = IncidentReport.objects.create(
            team=team1,
            submitted_by=users["blue1"],
            attack_description="Port scan detected",
            source_ip="192.168.1.50",
            destination_ip="10.100.11.25",
            affected_boxes=["Database Server"],
            affected_service="PostgreSQL",
            attack_detected_at=timezone.now(),
            attack_mitigated=True,
            gold_team_reviewed=False,
        )

        # Gold Team reviews and matches
        incident.gold_team_reviewed = True
        incident.matched_to_red_finding = red_finding
        incident.points_returned = Decimal("25.00")
        incident.reviewer_notes = "Valid detection, partial mitigation"
        incident.reviewed_by = users["gold"]
        incident.reviewed_at = timezone.now()
        incident.save()

        # Verify workflow state after review
        incident.refresh_from_db()
        assert incident.gold_team_reviewed is True
        assert incident.matched_to_red_finding == red_finding
        assert incident.points_returned == Decimal("25.00")
        assert incident.reviewed_by == users["gold"]
        assert incident.reviewed_at is not None
        assert incident.reviewer_notes == "Valid detection, partial mitigation"

    def test_step4_gold_team_rejects_incident(self, setup_teams, setup_users):
        """Step 4: Gold Team rejects invalid incident."""
        team1, team2 = setup_teams
        users = setup_users

        # Create incident
        incident = IncidentReport.objects.create(
            team=team1,
            submitted_by=users["blue1"],
            attack_description="False positive - routine maintenance",
            source_ip="192.168.1.200",
            destination_ip="10.100.11.30",
            affected_boxes=["Web Server"],
            affected_service="HTTP",
            attack_detected_at=timezone.now(),
            attack_mitigated=False,
            gold_team_reviewed=False,
        )

        # Gold Team reviews and rejects
        incident.gold_team_reviewed = True
        incident.matched_to_red_finding = None
        incident.points_returned = Decimal("0.00")
        incident.reviewer_notes = "Not a valid attack - routine maintenance activity"
        incident.reviewed_by = users["gold"]
        incident.reviewed_at = timezone.now()
        incident.save()

        # Verify rejection state
        incident.refresh_from_db()
        assert incident.gold_team_reviewed is True
        assert incident.matched_to_red_finding is None
        assert incident.points_returned == Decimal("0.00")
        assert incident.reviewed_by == users["gold"]

    def test_step5_points_calculated_correctly(self, setup_teams, setup_users):
        """Step 5: Verify point calculations are correct."""
        team1, team2 = setup_teams
        users = setup_users

        # Create Red Team finding worth 100 points
        red_finding = RedTeamFinding.objects.create(
            submitted_by=users["red"],
            attack_vector="Exploit attempt",
            source_ip="192.168.1.75",
            affected_boxes=["Application Server"],
            affected_service="Tomcat",
            universally_attempted=False,
            persistence_established=True,
            points_per_team=Decimal("100.00"),
            is_approved=True,
            approved_by=users["gold"],
            approved_at=timezone.now(),
        )
        red_finding.affected_teams.add(team1)

        # Create matched incident with 50 points recovery
        incident = IncidentReport.objects.create(
            team=team1,
            submitted_by=users["blue1"],
            attack_description="Exploit detected and blocked",
            source_ip="192.168.1.75",
            destination_ip="10.100.11.40",
            affected_boxes=["Application Server"],
            affected_service="Tomcat",
            attack_detected_at=timezone.now(),
            attack_mitigated=True,
            gold_team_reviewed=True,
            matched_to_red_finding=red_finding,
            points_returned=Decimal("50.00"),
            reviewed_by=users["gold"],
            reviewed_at=timezone.now(),
        )

        # Verify data integrity for scoring
        assert incident.points_returned == Decimal("50.00")
        assert incident.matched_to_red_finding.points_per_team == Decimal("100.00")
        assert incident.team in red_finding.affected_teams.all()


class TestRedTeamFindingWorkflow:
    """Test complete Red Team finding workflow from submission to approval."""

    def test_step1_red_team_submits_finding(self, setup_teams, setup_users):
        """Step 1: Red Team submits finding - verify initial state."""
        team1, team2 = setup_teams
        users = setup_users

        finding = RedTeamFinding.objects.create(
            submitted_by=users["red"],
            attack_vector="SSH brute force attack successful",
            source_ip="192.168.100.50",
            destination_ip_template="10.100.1X.22",
            affected_boxes=["Web Server"],
            affected_service="SSH",
            universally_attempted=True,
            persistence_established=False,
            points_per_team=Decimal("75.00"),
            notes="Weak passwords on SSH service",
        )
        finding.affected_teams.add(team1, team2)

        # Verify initial workflow state
        assert finding.submitted_by == users["red"]
        assert finding.points_per_team == Decimal("75.00")
        assert finding.is_approved is False
        assert finding.approved_by is None
        assert finding.approved_at is None
        assert finding.affected_teams.count() == 2

    def test_step2_finding_appears_pending(self, setup_teams, setup_users):
        """Step 2: Unapproved finding appears in pending list."""
        team1, team2 = setup_teams
        users = setup_users

        # Create unapproved finding
        finding = RedTeamFinding.objects.create(
            submitted_by=users["red"],
            attack_vector="SQL injection successful",
            source_ip="192.168.100.25",
            affected_boxes=["Database Server"],
            affected_service="MySQL",
            universally_attempted=False,
            persistence_established=True,
            points_per_team=Decimal("150.00"),
            is_approved=False,
        )
        finding.affected_teams.add(team1)

        # Verify finding is in pending state
        pending_findings = RedTeamFinding.objects.filter(is_approved=False)
        assert finding in pending_findings
        assert pending_findings.count() == 1

    def test_step3_gold_team_approves_finding(self, setup_teams, setup_users):
        """Step 3: Gold Team approves finding - verify approval fields."""
        team1, team2 = setup_teams
        users = setup_users

        # Create unapproved finding
        finding = RedTeamFinding.objects.create(
            submitted_by=users["red"],
            attack_vector="Privilege escalation exploit",
            source_ip="192.168.100.75",
            affected_boxes=["Domain Controller"],
            affected_service="LDAP",
            universally_attempted=False,
            persistence_established=True,
            points_per_team=Decimal("200.00"),
            is_approved=False,
        )
        finding.affected_teams.add(team1, team2)

        # Gold Team approves
        finding.is_approved = True
        finding.approved_by = users["gold"]
        finding.approved_at = timezone.now()
        finding.save()

        # Verify approval fields set correctly
        finding.refresh_from_db()
        assert finding.is_approved is True
        assert finding.approved_by == users["gold"]
        assert finding.approved_at is not None
        assert (timezone.now() - finding.approved_at).total_seconds() < 5

    def test_step4_bulk_approve_multiple_findings(self, setup_teams, setup_users):
        """Step 4: Bulk approve multiple findings."""
        team1, team2 = setup_teams
        users = setup_users

        # Create multiple unapproved findings
        finding1 = RedTeamFinding.objects.create(
            submitted_by=users["red"],
            attack_vector="Web shell upload",
            source_ip="192.168.100.10",
            affected_boxes=["Web Server"],
            affected_service="HTTP",
            universally_attempted=True,
            persistence_established=True,
            points_per_team=Decimal("100.00"),
            is_approved=False,
        )
        finding1.affected_teams.add(team1, team2)

        finding2 = RedTeamFinding.objects.create(
            submitted_by=users["red"],
            attack_vector="Password dump via mimikatz",
            source_ip="192.168.100.15",
            affected_boxes=["Domain Controller"],
            affected_service="SMB",
            universally_attempted=False,
            persistence_established=True,
            points_per_team=Decimal("250.00"),
            is_approved=False,
        )
        finding2.affected_teams.add(team1)

        # Bulk approve
        approval_time = timezone.now()
        for finding in [finding1, finding2]:
            finding.is_approved = True
            finding.approved_by = users["gold"]
            finding.approved_at = approval_time
            finding.save()

        # Verify both approved with correct fields
        finding1.refresh_from_db()
        finding2.refresh_from_db()
        assert finding1.is_approved is True
        assert finding1.approved_by == users["gold"]
        assert finding2.is_approved is True
        assert finding2.approved_by == users["gold"]


class TestOrangeAdjustmentWorkflow:
    """Test complete Orange Team adjustment workflow."""

    def test_step1_orange_team_submits_adjustment(self, setup_teams, setup_users):
        """Step 1: Orange Team submits adjustment - verify initial state."""
        team1, team2 = setup_teams
        users = setup_users

        check_type = OrangeCheckType.objects.create(name="Customer Service")

        adjustment = OrangeTeamScore.objects.create(
            team=team1,
            submitted_by=users["orange"],
            check_type=check_type,
            description="Excellent customer interaction and problem solving",
            points_awarded=Decimal("10.00"),
        )

        # Verify initial workflow state
        assert adjustment.team == team1
        assert adjustment.submitted_by == users["orange"]
        assert adjustment.points_awarded == Decimal("10.00")
        assert adjustment.is_approved is False
        assert adjustment.approved_by is None
        assert adjustment.approved_at is None

    def test_step2_adjustment_appears_pending(self, setup_teams, setup_users):
        """Step 2: Unapproved adjustment appears in pending list."""
        team1, team2 = setup_teams
        users = setup_users

        check_type = OrangeCheckType.objects.create(name="Professionalism")

        adjustment = OrangeTeamScore.objects.create(
            team=team1,
            submitted_by=users["orange"],
            check_type=check_type,
            description="Professional communication",
            points_awarded=Decimal("5.00"),
            is_approved=False,
        )

        # Verify adjustment is pending
        pending_adjustments = OrangeTeamScore.objects.filter(is_approved=False)
        assert adjustment in pending_adjustments
        assert pending_adjustments.count() == 1

    def test_step3_gold_team_approves_adjustment(self, setup_teams, setup_users):
        """Step 3: Gold Team approves adjustment - verify approval tracking."""
        team1, team2 = setup_teams
        users = setup_users

        check_type = OrangeCheckType.objects.create(name="Technical Knowledge")

        adjustment = OrangeTeamScore.objects.create(
            team=team1,
            submitted_by=users["orange"],
            check_type=check_type,
            description="Demonstrated excellent troubleshooting",
            points_awarded=Decimal("15.00"),
            is_approved=False,
        )

        # Gold Team approves
        adjustment.is_approved = True
        adjustment.approved_by = users["gold"]
        adjustment.approved_at = timezone.now()
        adjustment.save()

        # Verify approval tracking works
        adjustment.refresh_from_db()
        assert adjustment.is_approved is True
        assert adjustment.approved_by == users["gold"]
        assert adjustment.approved_at is not None

    def test_step4_gold_team_rejects_adjustment(self, setup_teams, setup_users):
        """Step 4: Gold Team rejects adjustment."""
        team1, team2 = setup_teams
        users = setup_users

        check_type = OrangeCheckType.objects.create(name="Responsiveness")

        adjustment = OrangeTeamScore.objects.create(
            team=team1,
            submitted_by=users["orange"],
            check_type=check_type,
            description="Questionable justification",
            points_awarded=Decimal("20.00"),
            is_approved=False,
        )

        adjustment_id = adjustment.pk

        # Gold Team rejects (deletes)
        adjustment.delete()

        # Verify adjustment is deleted
        assert not OrangeTeamScore.objects.filter(pk=adjustment_id).exists()


class TestInjectScoreWorkflow:
    """Test complete inject grade workflow."""

    def test_step1_white_team_grades_inject(self, setup_teams, setup_users):
        """Step 1: White Team grades inject - verify initial state."""
        team1, team2 = setup_teams
        users = setup_users

        grade = InjectScore.objects.create(
            team=team1,
            inject_id="INJ-001",
            inject_name="Network Diagram",
            max_points=Decimal("100.00"),
            points_awarded=Decimal("85.00"),
            notes="Good diagram, missing some details",
            graded_by=users["white"],
        )

        # Verify initial workflow state
        assert grade.team == team1
        assert grade.points_awarded == Decimal("85.00")
        assert grade.max_points == Decimal("100.00")
        assert grade.graded_by == users["white"]
        assert grade.is_approved is False
        assert grade.approved_by is None
        assert grade.approved_at is None

    def test_step2_grade_appears_in_review(self, setup_teams, setup_users):
        """Step 2: Unapproved grade appears in review list."""
        team1, team2 = setup_teams
        users = setup_users

        grade = InjectScore.objects.create(
            team=team1,
            inject_id="INJ-002",
            inject_name="Incident Response Plan",
            max_points=Decimal("150.00"),
            points_awarded=Decimal("120.00"),
            notes="Comprehensive plan",
            graded_by=users["white"],
            is_approved=False,
        )

        # Verify grade is in review list
        unapproved_grades = InjectScore.objects.filter(is_approved=False)
        assert grade in unapproved_grades
        assert unapproved_grades.count() == 1

    def test_step3_gold_team_approves_grade(self, setup_teams, setup_users):
        """Step 3: Gold Team approves grade - verify approval fields."""
        team1, team2 = setup_teams
        users = setup_users

        grade = InjectScore.objects.create(
            team=team1,
            inject_id="INJ-003",
            inject_name="Security Presentation",
            max_points=Decimal("200.00"),
            points_awarded=Decimal("175.00"),
            notes="Excellent presentation",
            graded_by=users["white"],
            is_approved=False,
        )

        # Gold Team approves
        grade.is_approved = True
        grade.approved_by = users["gold"]
        grade.approved_at = timezone.now()
        grade.save()

        # Verify approval fields set correctly
        grade.refresh_from_db()
        assert grade.is_approved is True
        assert grade.approved_by == users["gold"]
        assert grade.approved_at is not None

    def test_step4_outlier_detection_data(self, setup_teams, setup_users):
        """Step 4: Verify outlier detection has necessary data."""
        team1, team2 = setup_teams
        users = setup_users

        # Create several grades for same inject
        InjectScore.objects.create(
            team=team1,
            inject_id="INJ-004",
            inject_name="Business Continuity Plan",
            max_points=Decimal("100.00"),
            points_awarded=Decimal("75.00"),
            graded_by=users["white"],
            is_approved=True,
            approved_by=users["gold"],
            approved_at=timezone.now(),
        )

        InjectScore.objects.create(
            team=team2,
            inject_id="INJ-004",
            inject_name="Business Continuity Plan",
            max_points=Decimal("100.00"),
            points_awarded=Decimal("80.00"),
            graded_by=users["white"],
            is_approved=True,
            approved_by=users["gold"],
            approved_at=timezone.now(),
        )

        # Create outlier grade
        team3 = Team.objects.create(team_name="Blue Team 3", team_number=3, max_members=10)
        InjectScore.objects.create(
            team=team3,
            inject_id="INJ-004",
            inject_name="Business Continuity Plan",
            max_points=Decimal("100.00"),
            points_awarded=Decimal("99.00"),
            graded_by=users["white"],
            is_approved=False,
        )

        # Verify data exists for outlier detection
        all_grades_for_inject = InjectScore.objects.filter(inject_id="INJ-004")
        assert all_grades_for_inject.count() == 3
        points = [g.points_awarded for g in all_grades_for_inject]
        assert Decimal("75.00") in points
        assert Decimal("80.00") in points
        assert Decimal("99.00") in points
