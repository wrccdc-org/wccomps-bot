"""Business logic for the challenges (orange team) app."""

import random

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from challenges.models import (
    OrangeAssignment,
    OrangeAssignmentResult,
    OrangeCheck,
)
from scoring.models import OrangeTeamScore
from team.models import Team


def assign_teams_round_robin(
    check: OrangeCheck,
    checked_in_users: list[User],
    teams: list[Team],
) -> int:
    """Assign teams to checked-in users using round-robin distribution.

    Creates OrangeAssignment and OrangeAssignmentResult records.
    Returns the number of assignments created.
    """
    random.shuffle(teams)
    criteria = list(check.criteria.all())
    count = 0

    with transaction.atomic():
        for i, team in enumerate(teams):
            assigned_user = checked_in_users[i % len(checked_in_users)]
            # Skip if assignment already exists for this check+team
            if OrangeAssignment.objects.filter(orange_check=check, team=team).exists():
                continue
            assignment = OrangeAssignment.objects.create(
                orange_check=check,
                user=assigned_user,
                team=team,
            )
            # Create result rows for each criterion
            for criterion in criteria:
                OrangeAssignmentResult.objects.create(
                    assignment=assignment,
                    criterion=criterion,
                    met=False,
                )
            count += 1

        check.status = "active"
        check.save()

    return count


def create_orange_score_from_assignment(
    assignment: OrangeAssignment,
    approver: User,
) -> OrangeTeamScore:
    """Create an OrangeTeamScore record from an approved assignment.

    Returns the created OrangeTeamScore instance.
    """
    return OrangeTeamScore.objects.create(
        team=assignment.team,
        submitted_by=assignment.user,
        description=f"Check: {assignment.orange_check.title}",
        points_awarded=assignment.score or 0,
        is_approved=True,
        approved_by=approver,
        approved_at=timezone.now(),
    )
