"""
Red Team Finding deduplication logic.

Handles detection of duplicate submissions and merging of source IPs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.contrib.auth.models import User
from django.db import transaction

from team.models import Team

from .models import AttackType, RedTeamFinding, RedTeamIPPool

if TYPE_CHECKING:
    from django.db.models import QuerySet


@dataclass
class SubmissionResult:
    """Result of processing a red team finding submission."""

    status: str  # "created", "merged", "partial_merge"
    finding: RedTeamFinding
    message: str
    teams_added: list[Team]
    original_submitter: User | None = None
    ips_merged: bool = False


def find_duplicate_finding(
    attack_type: AttackType,
    boxes: list[str],
    teams: QuerySet[Team] | list[Team],
) -> tuple[RedTeamFinding | None, set[Team]]:
    """
    Find an existing finding that matches the submission criteria.

    Matching criteria:
    - Same attack type
    - Any box overlap (submitted boxes ∩ existing boxes)
    - Any team overlap (submitted teams ∩ existing teams)

    Returns:
        - existing_finding: The duplicate finding if found, None otherwise
        - uncovered_teams: Teams in submission not covered by existing finding
    """
    submitted_boxes = set(boxes)
    submitted_teams = set(teams)

    # Find findings with same attack type
    candidates = RedTeamFinding.objects.filter(
        attack_type=attack_type,
    ).prefetch_related("affected_teams")

    for candidate in candidates:
        existing_boxes = set(candidate.affected_boxes or [])

        # Check for any box overlap
        if not submitted_boxes.intersection(existing_boxes):
            continue

        existing_teams = set(candidate.affected_teams.all())

        # Check for any team overlap
        overlap = existing_teams.intersection(submitted_teams)
        if overlap:
            uncovered = submitted_teams - existing_teams
            return candidate, uncovered

    return None, submitted_teams


def merge_source_ips(
    finding: RedTeamFinding,
    new_ip: str | None,
    new_pool: RedTeamIPPool | None,
) -> bool:
    """
    Merge new source IP(s) into existing finding.

    Returns True if any new IPs were added.
    """
    # Collect all existing IPs
    existing_ips: set[str] = set()
    if finding.source_ip:
        existing_ips.add(str(finding.source_ip))
    if finding.source_ip_pool:
        existing_ips.update(finding.source_ip_pool.get_ip_list())

    # Collect new IPs
    new_ips: set[str] = set()
    if new_ip:
        new_ips.add(new_ip)
    if new_pool:
        new_ips.update(new_pool.get_ip_list())

    # Check if there are actually new IPs to add
    truly_new = new_ips - existing_ips
    if not truly_new:
        return False

    combined = existing_ips | new_ips

    if len(combined) == 1:
        # Single IP - use source_ip field
        finding.source_ip = list(combined)[0]
        finding.source_ip_pool = None
    else:
        # Multiple IPs - need a pool
        if finding.source_ip_pool:
            # Update existing pool
            finding.source_ip_pool.ip_addresses = "\n".join(sorted(combined))
            finding.source_ip_pool.save()
        elif finding.submitted_by:
            # Create a new merged pool
            pool = RedTeamIPPool.objects.create(
                name=f"Finding #{finding.id} IPs (merged)",
                ip_addresses="\n".join(sorted(combined)),
                created_by=finding.submitted_by,
            )
            finding.source_ip = None
            finding.source_ip_pool = pool

    finding.save()
    return True


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
    Process a red team finding submission with deduplication.

    This function:
    1. Checks for existing findings with the same attack type + box + team overlap
    2. If found: merges IPs, adds contributor, adds any new teams
    3. If not found: creates new finding

    Returns a SubmissionResult with details about what happened.
    """
    teams_list = list(teams)

    # Check for duplicate
    existing_finding, uncovered_teams = find_duplicate_finding(
        attack_type=attack_type,
        boxes=boxes,
        teams=teams_list,
    )

    if existing_finding:
        # Merge into existing finding
        ips_merged = merge_source_ips(existing_finding, source_ip, source_ip_pool)

        # Add contributor
        existing_finding.contributors.add(submitter)

        # Add any new teams
        teams_added = list(uncovered_teams)
        if teams_added:
            existing_finding.affected_teams.add(*teams_added)

        # Append notes if provided
        if notes:
            if existing_finding.notes:
                existing_finding.notes += f"\n\n[{submitter.username}]: {notes}"
            else:
                existing_finding.notes = f"[{submitter.username}]: {notes}"
            existing_finding.save()

        # Determine message
        if teams_added and ips_merged:
            message = (
                f"Combined with existing finding #{existing_finding.id}. "
                f"Teams {', '.join(t.team_name for t in teams_added)} added. "
                f"Your IP(s) were merged."
            )
            status = "partial_merge"
        elif teams_added:
            message = (
                f"Combined with existing finding #{existing_finding.id}. "
                f"Teams {', '.join(t.team_name for t in teams_added)} added."
            )
            status = "partial_merge"
        elif ips_merged:
            message = (
                f"This attack was already submitted (Finding #{existing_finding.id} "
                f"by {existing_finding.submitted_by.username if existing_finding.submitted_by else 'unknown'}). "
                f"Your IP(s) were added."
            )
            status = "merged"
        else:
            message = (
                f"This attack was already submitted (Finding #{existing_finding.id} "
                f"by {existing_finding.submitted_by.username if existing_finding.submitted_by else 'unknown'})."
            )
            status = "merged"

        return SubmissionResult(
            status=status,
            finding=existing_finding,
            message=message,
            teams_added=teams_added,
            original_submitter=existing_finding.submitted_by,
            ips_merged=ips_merged,
        )

    # No duplicate - create new finding
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

    finding = RedTeamFinding.objects.create(
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
