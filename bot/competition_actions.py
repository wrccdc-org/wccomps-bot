"""Shared competition actions for commands and timer."""

import logging
from typing import Any

from asgiref.sync import sync_to_async

from bot.authentik_manager import AuthentikManager
from bot.authentik_utils import toggle_all_blueteam_accounts
from core.models import CompetitionConfig

logger = logging.getLogger(__name__)


async def start_competition() -> dict[str, Any]:
    """
    Start the competition by enabling applications and accounts.

    Returns:
        Dict with keys: success, apps_enabled, apps_failed, accounts_enabled,
        accounts_failed, quotient_synced, errors
    """
    config = await sync_to_async(CompetitionConfig.get_config)()

    if not config.controlled_applications:
        return {
            "success": False,
            "error": "No controlled applications configured",
        }

    # Enable applications via Authentik API
    auth_manager = AuthentikManager()
    app_results = auth_manager.enable_applications(config.controlled_applications)

    # Enable all blueteam accounts
    accounts_enabled, accounts_failed = await toggle_all_blueteam_accounts(is_active=True)

    # Sync Quotient metadata
    try:
        from scoring.quotient_sync import sync_quotient_metadata

        await sync_to_async(sync_quotient_metadata)()
        quotient_synced = True
    except Exception as e:
        logger.warning(f"Failed to sync Quotient metadata: {e}")
        quotient_synced = False

    # Update config - clear start_time only, preserve end_time
    @sync_to_async
    def update_config():
        config.applications_enabled = True
        config.competition_start_time = None
        config.save()

    await update_config()

    # Build results
    success_apps = [app for app, (success, _) in app_results.items() if success]
    failed_apps = [(app, error) for app, (success, error) in app_results.items() if not success]

    return {
        "success": True,
        "apps_enabled": success_apps,
        "apps_failed": failed_apps,
        "accounts_enabled": accounts_enabled,
        "accounts_failed": accounts_failed,
        "quotient_synced": quotient_synced,
        "controlled_apps": config.controlled_applications,
    }


async def stop_competition() -> dict[str, Any]:
    """
    Stop the competition by disabling applications and accounts.

    Returns:
        Dict with keys: success, apps_disabled, apps_failed, accounts_disabled,
        accounts_failed
    """
    config = await sync_to_async(CompetitionConfig.get_config)()

    if not config.controlled_applications:
        return {
            "success": False,
            "error": "No controlled applications configured",
        }

    # Disable applications via Authentik API
    auth_manager = AuthentikManager()
    app_results = auth_manager.disable_applications(config.controlled_applications)

    # Disable all blueteam accounts
    accounts_disabled, accounts_failed = await toggle_all_blueteam_accounts(is_active=False)

    # Update config - clear end_time only, preserve start_time
    @sync_to_async
    def update_config():
        config.applications_enabled = False
        config.competition_end_time = None
        config.save()

    await update_config()

    # Build results
    success_apps = [app for app, (success, _) in app_results.items() if success]
    failed_apps = [(app, error) for app, (success, error) in app_results.items() if not success]

    return {
        "success": True,
        "apps_disabled": success_apps,
        "apps_failed": failed_apps,
        "accounts_disabled": accounts_disabled,
        "accounts_failed": accounts_failed,
        "controlled_apps": config.controlled_applications,
    }
