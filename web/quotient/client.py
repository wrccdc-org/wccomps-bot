"""Client for Quotient scoring engine REST API."""

import logging
from dataclasses import dataclass
from functools import lru_cache

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


@dataclass
class QuotientService:
    """Represents a service on a box."""

    name: str
    display_name: str
    type: str  # custom, dns, smtp, imap, ssh, web, pop3


@dataclass
class QuotientBox:
    """Represents an infrastructure box."""

    name: str
    ip: str
    services: list[QuotientService]


@dataclass
class QuotientInfrastructure:
    """Complete infrastructure from Quotient."""

    boxes: list[QuotientBox]
    event_name: str
    team_count: int
    api_version: str


@dataclass
class TeamScore:
    """Team scoring data from Quotient."""

    team_name: str
    team_number: int
    total_score: float
    score_history: list[dict[str, int | float]]  # [{Round: int, Total: float}, ...]


@dataclass
class Inject:
    """Inject from Quotient."""

    inject_id: int
    title: str
    description: str
    open_time: str | None
    due_time: str | None
    close_time: str | None
    files: list[str]
    submissions: list[dict[str, str | int]]  # [{TeamID, InjectID, SubmissionTime, ...}, ...]


class QuotientAPIError(Exception):
    """Raised when Quotient API returns an error."""


class QuotientClient:
    """Client for Quotient scoring engine REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        cache_ttl: int = 300,  # 5 minutes
    ):
        """
        Initialize Quotient API client.

        Args:
            base_url: URL for Quotient API (default from settings)
            cache_ttl: Cache time-to-live in seconds (default 300)
        """
        base = base_url or str(getattr(settings, "QUOTIENT_API_URL", ""))
        self.base_url = base.rstrip("/")
        self.cache_ttl = cache_ttl
        self.session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        """Get or create authenticated session."""
        if self.session is None:
            self.session = requests.Session()

            # Use hardcoded admin credentials from settings
            username = getattr(settings, "QUOTIENT_USERNAME", "")
            password = getattr(settings, "QUOTIENT_PASSWORD", "")

            if not username or not password:
                logger.error("QUOTIENT_USERNAME or QUOTIENT_PASSWORD not configured")
                raise QuotientAPIError("Quotient credentials not configured")

            try:
                response = self.session.post(
                    f"{self.base_url}/api/login",
                    json={
                        "username": username,
                        "password": password,
                    },
                    timeout=10,
                )
                response.raise_for_status()
                logger.info(f"Authenticated with Quotient as {username}")
                return self.session
            except requests.RequestException as e:
                logger.exception(f"Failed to authenticate with Quotient: {e}")
                raise QuotientAPIError(f"Authentication failed: {e}") from e

        return self.session

    def get_infrastructure(self, force_refresh: bool = False) -> QuotientInfrastructure | None:
        """
        Fetch infrastructure from Quotient API.

        Args:
            force_refresh: Skip cache and fetch fresh data

        Returns:
            QuotientInfrastructure object or None if unavailable
        """
        cache_key = "quotient_infrastructure"

        # Check cache first
        if not force_refresh:
            cached: QuotientInfrastructure | None = cache.get(cache_key)
            if cached:
                logger.debug("Returning cached infrastructure")
                return cached

        try:
            session = self._get_session()
            response = session.get(f"{self.base_url}/api/metadata", timeout=10)
            response.raise_for_status()

            data = response.json()

            # Parse response into dataclasses
            # /api/metadata returns: {"boxes": [{"name": str, "ip": str, "services": [str]}]}
            boxes = []
            for box_data in data.get("boxes", []):
                # Services are just strings (display names) in metadata endpoint
                services = [
                    QuotientService(
                        name=svc_name,
                        display_name=svc_name,
                        type="custom",  # Type not provided by metadata endpoint
                    )
                    for svc_name in box_data.get("services", [])
                ]

                boxes.append(
                    QuotientBox(
                        name=box_data["name"],
                        ip=box_data["ip"],
                        services=services,
                    )
                )

            infrastructure = QuotientInfrastructure(
                boxes=boxes,
                event_name="",  # Not provided by metadata endpoint
                team_count=0,  # Not provided by metadata endpoint
                api_version="v1",
            )

            # Cache the result
            cache.set(cache_key, infrastructure, self.cache_ttl)
            logger.info(f"Fetched {len(boxes)} boxes from Quotient API")

            return infrastructure

        except requests.RequestException as e:
            logger.exception(f"Failed to fetch infrastructure from Quotient: {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.exception(f"Failed to parse infrastructure response: {e}")
            return None

    def get_scores(self, force_refresh: bool = False) -> list[TeamScore] | None:
        """
        Fetch team scores from Quotient API.

        Args:
            force_refresh: Skip cache and fetch fresh data

        Returns:
            List of TeamScore objects or None if unavailable
        """
        cache_key = "quotient_scores"

        if not force_refresh:
            cached: list[TeamScore] | None = cache.get(cache_key)
            if cached:
                return cached

        try:
            session = self._get_session()
            response = session.get(f"{self.base_url}/api/graphs/scores", timeout=10)
            response.raise_for_status()

            data = response.json()
            scores = []
            for team_data in data.get("series", []):
                team_name = team_data["Name"]
                # Extract team number from name (e.g., "team09" -> 9)
                team_num = int("".join(c for c in team_name if c.isdigit()) or "0")
                history = team_data.get("Data", [])
                total = history[-1]["Total"] if history else 0

                scores.append(
                    TeamScore(
                        team_name=team_name,
                        team_number=team_num,
                        total_score=float(total),
                        score_history=history,
                    )
                )

            cache.set(cache_key, scores, self.cache_ttl)
            logger.info(f"Fetched scores for {len(scores)} teams")
            return scores

        except requests.RequestException as e:
            logger.exception(f"Failed to fetch scores from Quotient: {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.exception(f"Failed to parse scores response: {e}")
            return None

    def get_team_count(self) -> int | None:
        """Get the number of teams from Quotient scores."""
        scores = self.get_scores()
        if scores is None:
            return None
        return len(scores)

    def get_injects(self, force_refresh: bool = False) -> list[Inject] | None:
        """
        Fetch injects from Quotient API.

        Returns:
            List of Inject objects or None if unavailable
        """
        cache_key = "quotient_injects"

        if not force_refresh:
            cached: list[Inject] | None = cache.get(cache_key)
            if cached:
                return cached

        try:
            session = self._get_session()
            response = session.get(f"{self.base_url}/api/injects", timeout=10)
            response.raise_for_status()

            data = response.json()
            # API returns a list directly
            inject_list = data if isinstance(data, list) else data.get("injects", [])

            injects = [
                Inject(
                    inject_id=i["ID"],
                    title=i["Title"],
                    description=i["Description"],
                    open_time=i.get("OpenTime"),
                    due_time=i.get("DueTime"),
                    close_time=i.get("CloseTime"),
                    files=i.get("InjectFileNames", []),
                    submissions=i.get("Submissions", []),
                )
                for i in inject_list
            ]

            cache.set(cache_key, injects, 60)  # 1 minute cache
            logger.info(f"Fetched {len(injects)} injects")
            return injects

        except requests.RequestException as e:
            logger.exception(f"Failed to fetch injects from Quotient: {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.exception(f"Failed to parse injects response: {e}")
            return None

    def get_service_choices(self) -> list[dict[str, str]]:
        """
        Get formatted service choices for ticket dropdown.

        Returns:
            List of dicts with 'value', 'label', and 'box_ip' keys
        """
        infrastructure = self.get_infrastructure()
        if not infrastructure:
            return []

        choices = [
            {
                "value": f"{box.name}:{service.name}",
                "label": f"{box.name} - {service.display_name}",
                "box_ip": box.ip,
                "box_name": box.name,
                "service_name": service.name,
                "service_type": service.type,
            }
            for box in infrastructure.boxes
            for service in box.services
        ]

        return sorted(choices, key=lambda x: x["label"])

    def get_box_names(self) -> list[str]:
        """Get list of all box names."""
        infrastructure = self.get_infrastructure()
        if not infrastructure:
            return []

        return sorted([box.name for box in infrastructure.boxes])

    def clear_cache(self) -> None:
        """Clear all cached Quotient data."""
        cache.delete_many(
            [
                "quotient_infrastructure",
                "quotient_scores",
                "quotient_service_status",
                "quotient_uptimes",
                "quotient_injects",
            ]
        )
        logger.info("Cleared Quotient caches")


@lru_cache(maxsize=1)
def get_quotient_client() -> QuotientClient:
    """Get or create the global Quotient client instance."""
    return QuotientClient()
