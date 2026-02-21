from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.utils import timezone

from challenges.models import (
    OrangeAssignment,
    OrangeAssignmentResult,
    OrangeCheck,
    OrangeCheckCriterion,
    OrangeCheckIn,
    OrangeFollowUp,
)
from team.models import Team

pytestmark = pytest.mark.django_db


class TestOrangeCheckIn:
    def test_check_in(self) -> None:
        user = User.objects.create_user(username="orange1")
        checkin = OrangeCheckIn.objects.create(user=user)
        assert checkin.is_active
        assert checkin.checked_out_at is None

    def test_only_one_active_checkin(self) -> None:
        user = User.objects.create_user(username="orange1")
        OrangeCheckIn.objects.create(user=user)
        with pytest.raises(IntegrityError):
            OrangeCheckIn.objects.create(user=user)


class TestOrangeCheck:
    def test_create_check(self) -> None:
        user = User.objects.create_user(username="lead1")
        check = OrangeCheck.objects.create(
            title="Password Reset", description="Ask team to reset password", created_by=user
        )
        assert check.status == "draft"
        assert check.max_score == 0

    def test_max_score_from_criteria(self) -> None:
        check = OrangeCheck.objects.create(title="Test", description="Test")
        OrangeCheckCriterion.objects.create(orange_check=check, label="Fast response", points=3)
        OrangeCheckCriterion.objects.create(orange_check=check, label="Professional", points=3)
        OrangeCheckCriterion.objects.create(orange_check=check, label="Resolved", points=4)
        assert check.max_score == 10


class TestOrangeAssignment:
    def test_create_assignment(self) -> None:
        user = User.objects.create_user(username="orange1")
        team = Team.objects.create(team_number=1, team_name="Team 01")
        check = OrangeCheck.objects.create(title="Test", description="Test")
        assignment = OrangeAssignment.objects.create(orange_check=check, user=user, team=team)
        assert assignment.status == "pending"
        assert assignment.score is None

    def test_calculate_score(self) -> None:
        user = User.objects.create_user(username="orange1")
        team = Team.objects.create(team_number=1, team_name="Team 01")
        check = OrangeCheck.objects.create(title="Test", description="Test")
        c1 = OrangeCheckCriterion.objects.create(orange_check=check, label="Fast", points=3)
        c2 = OrangeCheckCriterion.objects.create(orange_check=check, label="Pro", points=3)
        c3 = OrangeCheckCriterion.objects.create(orange_check=check, label="Resolved", points=4)
        assignment = OrangeAssignment.objects.create(orange_check=check, user=user, team=team)
        OrangeAssignmentResult.objects.create(assignment=assignment, criterion=c1, met=True)
        OrangeAssignmentResult.objects.create(assignment=assignment, criterion=c2, met=False)
        OrangeAssignmentResult.objects.create(assignment=assignment, criterion=c3, met=True)
        assert assignment.calculate_score() == 7

    def test_unique_team_per_check(self) -> None:
        user1 = User.objects.create_user(username="orange1")
        user2 = User.objects.create_user(username="orange2")
        team = Team.objects.create(team_number=1, team_name="Team 01")
        check = OrangeCheck.objects.create(title="Test", description="Test")
        OrangeAssignment.objects.create(orange_check=check, user=user1, team=team)
        with pytest.raises(IntegrityError):
            OrangeAssignment.objects.create(orange_check=check, user=user2, team=team)


class TestOrangeFollowUp:
    def test_create_followup(self) -> None:
        user = User.objects.create_user(username="orange1")
        team = Team.objects.create(team_number=1, team_name="Team 01")
        check = OrangeCheck.objects.create(title="Test", description="Test")
        assignment = OrangeAssignment.objects.create(orange_check=check, user=user, team=team)
        followup = OrangeFollowUp.objects.create(
            user=user,
            assignment=assignment,
            remind_at=timezone.now() + timedelta(minutes=15),
            note="Check if they fixed the issue",
        )
        assert not followup.dismissed
