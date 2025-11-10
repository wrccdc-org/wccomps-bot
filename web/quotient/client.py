"""Client for Quotient scoring engine REST API."""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
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
    services: List[QuotientService]


@dataclass
class QuotientInfrastructure:
    """Complete infrastructure from Quotient."""

    boxes: List[QuotientBox]
    event_name: str
    team_count: int
    api_version: str


@dataclass
class TeamScore:
    """Team scoring data from Quotient."""

    team_number: int
    total_score: float
    service_score: float
    inject_score: float
    incident_score: float
    rank: int
    last_updated: str


@dataclass
class ServiceCheck:
    """Service check result from Quotient."""

    team_number: int
    box_name: str
    service_name: str
    is_up: bool
    response_time_ms: Optional[int]
    error_message: Optional[str]
    checked_at: str


@dataclass
class Inject:
    """Inject from Quotient."""

    inject_id: str
    title: str
    description: str
    points: int
    due_date: Optional[str]
    is_published: bool
    team_submissions: Dict[int, str]  # team_number -> status (pending, graded, etc)


class QuotientAPIError(Exception):
    """Raised when Quotient API returns an error."""

    pass


class QuotientClient:
    """Client for Quotient scoring engine REST API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        fallback_url: Optional[str] = None,
        admin_username: Optional[str] = None,
        admin_password: Optional[str] = None,
        oidc_token: Optional[str] = None,
        cache_ttl: int = 300,  # 5 minutes
    ):
        """
        Initialize Quotient API client.

        Args:
            base_url: Primary URL for Quotient API (default from settings)
            fallback_url: Fallback URL if primary fails (default from settings)
            admin_username: Admin username for authentication
            admin_password: Admin password for authentication
            oidc_token: OIDC token for authentication (takes precedence)
            cache_ttl: Cache time-to-live in seconds (default 300)
        """
        self.base_url = (base_url or getattr(settings, "QUOTIENT_API_URL", "")).rstrip(
            "/"
        )
        self.fallback_url = (
            fallback_url or getattr(settings, "QUOTIENT_FALLBACK_URL", "")
        ).rstrip("/")
        self.admin_username = admin_username or getattr(
            settings, "QUOTIENT_ADMIN_USERNAME", ""
        )
        self.admin_password = admin_password or getattr(
            settings, "QUOTIENT_ADMIN_PASSWORD", ""
        )
        self.oidc_token = oidc_token or getattr(settings, "QUOTIENT_OIDC_TOKEN", "")
        self.cache_ttl = cache_ttl
        self.session: Optional[requests.Session] = None
        self._active_url: Optional[str] = None

    def _get_session(self) -> requests.Session:
        """Get or create authenticated session."""
        if self.session is None:
            self.session = requests.Session()

            # Try OIDC token authentication first (for service-to-service)
            if self.oidc_token:
                try:
                    # Use OIDC token as password in login API
                    # Quotient accepts OIDC tokens via ValidateOIDCToken when username is empty
                    response = self.session.post(
                        f"{self._get_active_url()}/api/login",
                        json={
                            "username": "",
                            "password": self.oidc_token,
                        },
                        timeout=10,
                    )
                    response.raise_for_status()
                    logger.info("Authenticated with Quotient API using OIDC token")
                    return self.session
                except requests.RequestException as e:
                    logger.warning(f"OIDC authentication failed, falling back to username/password: {e}")

            # Fall back to username/password authentication
            if self.admin_username and self.admin_password:
                try:
                    response = self.session.post(
                        f"{self._get_active_url()}/api/login",
                        json={
                            "username": self.admin_username,
                            "password": self.admin_password,
                        },
                        timeout=10,
                    )
                    response.raise_for_status()
                    logger.info("Authenticated with Quotient API using credentials")
                except requests.RequestException as e:
                    logger.error(f"Failed to authenticate with Quotient: {e}")
                    raise QuotientAPIError(f"Authentication failed: {e}")
            else:
                logger.warning("No Quotient credentials configured, API calls may fail")

        return self.session

    def _get_active_url(self) -> str:
        """Get the currently active URL (primary or fallback)."""
        if self._active_url:
            return self._active_url
        return self.base_url

    def get_infrastructure(
        self, force_refresh: bool = False
    ) -> Optional[QuotientInfrastructure]:
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
            cached = cache.get(cache_key)
            if cached:
                logger.debug("Returning cached infrastructure")
                return cached

        # Try primary URL first, then fallback
        urls_to_try = [self.base_url]
        if self.fallback_url:
            urls_to_try.append(self.fallback_url)

        last_error = None
        for url_attempt in urls_to_try:
            self._active_url = url_attempt
            # Reset session for new URL
            self.session = None

            try:
                session = self._get_session()
                response = session.get(f"{url_attempt}/api/metadata", timeout=10)
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
                logger.info(f"Fetched {len(boxes)} boxes from Quotient API at {url_attempt}")

                return infrastructure

            except requests.RequestException as e:
                last_error = e
                logger.warning(f"Failed to fetch infrastructure from {url_attempt}: {e}")
                continue
            except (KeyError, ValueError) as e:
                last_error = e
                logger.warning(f"Failed to parse response from {url_attempt}: {e}")
                continue

        # All URLs failed
        logger.error(f"Failed to fetch infrastructure from all URLs. Last error: {last_error}")
        return None

    def get_scores(self, force_refresh: bool = False) -> Optional[List[TeamScore]]:
        """
        Fetch team scores from Quotient API.

        Args:
            force_refresh: Skip cache and fetch fresh data

        Returns:
            List of TeamScore objects or None if unavailable
        """
        cache_key = "quotient_scores"

        if not force_refresh:
            cached = cache.get(cache_key)
            if cached:
                return cached

        try:
            session = self._get_session()
            response = session.get(f"{self.base_url}/api/scores", timeout=10)
            response.raise_for_status()

            data = response.json()
            scores = [
                TeamScore(
                    team_number=s["team_number"],
                    total_score=s["total_score"],
                    service_score=s.get("service_score", 0),
                    inject_score=s.get("inject_score", 0),
                    incident_score=s.get("incident_score", 0),
                    rank=s["rank"],
                    last_updated=s.get("last_updated", ""),
                )
                for s in data.get("scores", [])
            ]

            cache.set(cache_key, scores, self.cache_ttl)
            logger.info(f"Fetched scores for {len(scores)} teams")
            return scores

        except requests.RequestException as e:
            logger.error(f"Failed to fetch scores from Quotient: {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.error(f"Failed to parse scores response: {e}")
            return None

    def get_service_checks(
        self, team_number: Optional[int] = None
    ) -> Optional[List[ServiceCheck]]:
        """
        Fetch service check results from Quotient API.

        Args:
            team_number: Filter for specific team (default: all teams)

        Returns:
            List of ServiceCheck objects or None if unavailable
        """
        try:
            session = self._get_session()
            url = f"{self.base_url}/api/service-checks"
            if team_number:
                url += f"?team={team_number}"

            response = session.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()
            checks = [
                ServiceCheck(
                    team_number=c["team_number"],
                    box_name=c["box_name"],
                    service_name=c["service_name"],
                    is_up=c["is_up"],
                    response_time_ms=c.get("response_time_ms"),
                    error_message=c.get("error_message"),
                    checked_at=c["checked_at"],
                )
                for c in data.get("checks", [])
            ]

            logger.info(f"Fetched {len(checks)} service checks")
            return checks

        except requests.RequestException as e:
            logger.error(f"Failed to fetch service checks from Quotient: {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.error(f"Failed to parse service checks response: {e}")
            return None

    def get_injects(self) -> Optional[List[Inject]]:
        """
        Fetch injects from Quotient API.

        Returns:
            List of Inject objects or None if unavailable
        """
        cache_key = "quotient_injects"
        cached = cache.get(cache_key)
        if cached:
            return cached

        try:
            session = self._get_session()
            response = session.get(f"{self.base_url}/api/injects", timeout=10)
            response.raise_for_status()

            data = response.json()
            injects = [
                Inject(
                    inject_id=i["id"],
                    title=i["title"],
                    description=i["description"],
                    points=i["points"],
                    due_date=i.get("due_date"),
                    is_published=i.get("is_published", False),
                    team_submissions=i.get("submissions", {}),
                )
                for i in data.get("injects", [])
            ]

            cache.set(cache_key, injects, 60)  # 1 minute cache
            logger.info(f"Fetched {len(injects)} injects")
            return injects

        except requests.RequestException as e:
            logger.error(f"Failed to fetch injects from Quotient: {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.error(f"Failed to parse injects response: {e}")
            return None

    def get_service_choices(self) -> List[Dict[str, str]]:
        """
        Get formatted service choices for ticket dropdown.

        Returns:
            List of dicts with 'value', 'label', and 'box_ip' keys
        """
        infrastructure = self.get_infrastructure()
        if not infrastructure:
            return []

        choices = []
        for box in infrastructure.boxes:
            for service in box.services:
                choices.append(
                    {
                        "value": f"{box.name}:{service.name}",
                        "label": f"{box.name} - {service.display_name}",
                        "box_ip": box.ip,
                        "box_name": box.name,
                        "service_name": service.name,
                        "service_type": service.type,
                    }
                )

        return sorted(choices, key=lambda x: x["label"])

    def get_box_names(self) -> List[str]:
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
                "quotient_injects",
            ]
        )
        logger.info("Cleared Quotient caches")


# Global client instance
_client: Optional[QuotientClient] = None


def get_quotient_client() -> QuotientClient:
    """Get or create the global Quotient client instance."""
    global _client
    if _client is None:
        _client = QuotientClient()
    return _client
