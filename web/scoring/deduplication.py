"""Red Team Score submission processing."""

from dataclasses import dataclass

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import QuerySet

from team.models import Team

from .models import AttackType, RedTeamIPPool, RedTeamScore


@dataclass
class SubmissionResult:
    """Result of processing a red team finding submission."""

    status: str  # "created"
    finding: RedTeamScore
    message: str
    teams_added: list[Team]


@dataclass
class OutcomeData:
    """Outcome checkboxes for CCDC scoring."""

    root_access: bool = False
    user_access: bool = False
    privilege_escalation: bool = False
    credentials_recovered: bool = False
    sensitive_files_recovered: bool = False
    credit_cards_recovered: bool = False
    pii_recovered: bool = False
    encrypted_db_recovered: bool = False
    db_decrypted: bool = False


@transaction.atomic
def process_red_team_submission(
    attack_type: AttackType,
    boxes: list[str],
    teams: QuerySet[Team] | list[Team],
    source_ip: str | None,
    source_ip_pool: RedTeamIPPool | None,
    submitter: User,
    notes: str = "",
    affected_service: str = "",
    destination_ip_template: str = "",
    universally_attempted: bool = False,
    persistence_established: bool = False,
    outcomes: OutcomeData | None = None,
) -> SubmissionResult:
    """
    Process a red team finding submission.

    Creates a new RedTeamScore with auto-calculated points.
    """
    teams_list = list(teams)
    outcome_fields = {}
    if outcomes:
        outcome_fields = {
            "root_access": outcomes.root_access,
            "user_access": outcomes.user_access,
            "privilege_escalation": outcomes.privilege_escalation,
            "credentials_recovered": outcomes.credentials_recovered,
            "sensitive_files_recovered": outcomes.sensitive_files_recovered,
            "credit_cards_recovered": outcomes.credit_cards_recovered,
            "pii_recovered": outcomes.pii_recovered,
            "encrypted_db_recovered": outcomes.encrypted_db_recovered,
            "db_decrypted": outcomes.db_decrypted,
        }

    finding = RedTeamScore.objects.create(
        attack_type=attack_type,
        affected_boxes=boxes,
        source_ip=source_ip if not source_ip_pool else None,
        source_ip_pool=source_ip_pool,
        submitted_by=submitter,
        notes=notes,
        affected_service=affected_service,
        destination_ip_template=destination_ip_template,
        universally_attempted=universally_attempted,
        persistence_established=persistence_established,
        points_per_team=0,  # Will be calculated below
        **outcome_fields,
    )
    # Auto-calculate points from outcomes
    finding.points_per_team = finding.calculate_points()
    finding.save(update_fields=["points_per_team"])

    finding.affected_teams.set(teams_list)
    finding.contributors.add(submitter)

    return SubmissionResult(
        status="created",
        finding=finding,
        message=f"Finding #{finding.id} created successfully.",
        teams_added=[],
    )
