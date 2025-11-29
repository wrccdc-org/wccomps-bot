# WCComps Documentation

## Specification Documents

### Current
- [User Roles and Stories](user-roles-and-stories.md) - Defines user roles, permissions, and user stories
- [UI Design System](ui-design-system.md) - Consistent patterns for navigation, layouts, components
- [Implementation Tasks](tasks.md) - Comprehensive task list with verification criteria

### Planned
- API Documentation - REST API endpoints and contracts
- Data Models - Database schema and relationships

## Quick Reference

### User Roles
| Role | Authentik Group | Primary Purpose |
|------|-----------------|-----------------|
| Blue Team | `WCComps_BlueTeam{N}` | Competition participants defending infrastructure |
| Red Team | `WCComps_RedTeam` | Attackers documenting successful attacks |
| Gold Team | `WCComps_GoldTeam` | Competition organizers and judges |
| White Team | `WCComps_WhiteTeam` | Inject graders |
| Orange Team | `WCComps_OrangeTeam` | Bonus/penalty adjustments |
| Ticketing Support | `WCComps_Ticketing_Support` | Handle participant support tickets |
| Ticketing Admin | `WCComps_Ticketing_Admin` | Elevated ticket management |
| Admin | `WCComps_Discord_Admin` | System administration |

### Key URLs
| Path | Purpose |
|------|---------|
| `/scoring/` | Leaderboard and scoring features |
| `/scoring/incident/submit/` | Blue team incident reports |
| `/scoring/red-team/submit/` | Red team finding submission |
| `/ops/tickets/` | Ticket management |
| `/ops/group-role-mappings/` | Team member mappings |
| `/ops/school-info/` | School contact information |
| `/admin/` | Django admin |
