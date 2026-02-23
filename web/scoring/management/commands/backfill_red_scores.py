"""Backfill red team scores with inferred box/service/attack_type from attack_vector + Quotient metadata."""

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from scoring.models import AttackType, QuotientMetadataCache, RedTeamScore

# Map keywords in attack_vector to AttackType names
ATTACK_TYPE_KEYWORDS: dict[str, str] = {
    "default creds": "Default Credentials",
    "cred reuse": "Credential Reuse",
    "persistence": "Persistence",
    "data leak": "Data Leakage",
    "rce": "Remote Code Execution",
    "wazuh": "Misconfiguration Exploit",
}

# Map keywords to service names (from Quotient service list)
SERVICE_KEYWORDS: dict[str, str] = {
    "wazuh": "wazuh",
    "ldap": "ldap",
    "ad manager": "ldap",
}

# Regex to extract octet: matches ".NNN" or "0.NNN" patterns
OCTET_RE = re.compile(r"(?:^|(?<=\s))\.?0?\.(\d+)\b")


def _build_octet_map(metadata: QuotientMetadataCache) -> dict[str, dict[str, object]]:
    """Build a map from last IP octet to box info."""
    octet_map: dict[str, dict[str, object]] = {}
    for box in metadata.boxes:
        ip = box.get("ip", "")
        if not ip:
            continue
        last_octet = ip.split(".")[-1]
        octet_map[last_octet] = {
            "name": box["name"],
            "services": [s["name"] for s in box.get("services", [])],
        }
    return octet_map


class Command(BaseCommand):
    """Backfill red team scores with inferred metadata from attack_vector strings."""

    help = "Backfill red team scores with box/service/attack_type inferred from attack_vector"

    def add_arguments(self, parser):  # type: ignore[no-untyped-def]
        """Add command arguments."""
        parser.add_argument("--dry-run", action="store_true", help="Preview changes without saving")

    @transaction.atomic
    def handle(self, *args: str, **options: object) -> None:
        """Execute the backfill."""
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved"))

        metadata = QuotientMetadataCache.objects.first()
        if not metadata:
            self.stderr.write(self.style.ERROR("No Quotient metadata cached. Run sync_metadata first."))
            return

        octet_map = _build_octet_map(metadata)
        self.stdout.write(
            f"Octet map: {', '.join(f'.{k}={v["name"]}' for k, v in sorted(octet_map.items(), key=lambda x: int(
                        x[0]
                    )))}"
        )

        # Pre-fetch attack types
        attack_types: dict[str, AttackType] = {}
        for at in AttackType.objects.all():
            attack_types[at.name.lower()] = at

        # Process only qualifier imports (attack_type is null)
        scores = RedTeamScore.objects.filter(attack_type__isnull=True).order_by("pk")
        total = scores.count()
        updated = 0

        for score in scores:
            vector = score.attack_vector.strip()
            vector_lower = vector.lower()
            changes: list[str] = []

            # 1. Extract octet and look up box
            octet_match = OCTET_RE.search(vector)
            if octet_match:
                octet = octet_match.group(1)
                box_info = octet_map.get(octet)
                if box_info:
                    box_name = str(box_info["name"])
                    if not score.affected_boxes:
                        score.affected_boxes = [box_name]
                        changes.append(f"box={box_name}")

                    # 2. Infer service from keywords
                    if not score.affected_service:
                        box_services = box_info["services"]
                        for keyword, service_name in SERVICE_KEYWORDS.items():
                            if keyword in vector_lower and service_name in box_services:  # type: ignore[operator]
                                score.affected_service = service_name
                                changes.append(f"service={service_name}")
                                break

            # 3. Infer attack type from keywords
            for keyword, at_name in ATTACK_TYPE_KEYWORDS.items():
                if keyword in vector_lower:
                    at = attack_types.get(at_name.lower())
                    if at:
                        score.attack_type = at
                        changes.append(f"attack_type={at_name}")
                    break

            # 4. Clean up attack_vector to just the description (remove octet prefix)
            # e.g. ".240 Wazuh" -> "Wazuh", "RCE .14" -> "RCE"
            # Only if we successfully mapped the box
            if score.affected_boxes and octet_match:
                cleaned = OCTET_RE.sub("", vector).strip()
                # Remove leading/trailing dots and whitespace
                cleaned = cleaned.strip(". ")
                if cleaned and cleaned != vector:
                    score.attack_vector = cleaned
                    changes.append(f"vector='{cleaned}'")

            if changes:
                self.stdout.write(f"  [{score.pk}] '{vector}' -> {', '.join(changes)}")
                if not dry_run:
                    score.save(update_fields=["affected_boxes", "affected_service", "attack_type", "attack_vector"])
                updated += 1
            else:
                self.stdout.write(f"  [{score.pk}] '{vector}' -> (no changes)")

        self.stdout.write(self.style.SUCCESS(f"\nDone: {updated}/{total} scores updated"))

        if dry_run:
            raise transaction.TransactionManagementError("DRY RUN — rolling back")
