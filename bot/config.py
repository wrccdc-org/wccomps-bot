"""Bot configuration — single source of truth for bot-side environment variables.

All bot-side environment variables should be read here, not scattered
across modules. Import from this module instead of calling os.environ directly.
"""

import os

DISCORD_GUILD_ID = int(os.environ.get("DISCORD_GUILD_ID", "0"))
VOLUNTEER_GUILD_ID = int(os.environ.get("VOLUNTEER_GUILD_ID", "0"))
DISCORD_ANNOUNCEMENT_CHANNEL_ID = int(os.environ.get("DISCORD_ANNOUNCEMENT_CHANNEL_ID", "0"))
BLUETEAM_ROLE_ID = int(os.environ.get("BLUETEAM_ROLE_ID", "0"))
