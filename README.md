# ER:LC Roblox ↔ Discord Bot

A production-minded Discord bot foundation for an ER:LC community. It has a
custom Roblox group verification flow, staff-posted information embeds, shift
tracking, Roblox role assignment, and separated administrative logs.

## What it includes

| Feature | How it works |
| --- | --- |
| Verification | `/verify` checks a Roblox username against your group, saves the link, maps Roblox roles to Discord roles, and applies a configurable nickname. A persistent button panel can also collect or refresh usernames. |
| Information embeds | Staff use `/embed` for one-off announcements, or publish fixed JSON templates with fields and link buttons. |
| Shifts | `/shift start`, `end`, `status`, `history`, and staff-only `active` record who is working and for how long. A live shift panel shows active members and their running timers. |
| Roblox promotions | `/promotion promote` assigns only allow-listed group roles through Roblox Open Cloud and permanently records every success or failure. |
| Administrator logs | Route verification, shift, promotion, moderation, member, and general administrative events to separate Discord channels. |
| Server helpers | `/server stats` gives live counts; `/server member` provides a private saved-record lookup. |

## First-time setup

1. Create a Discord application and bot, then enable **Server Members Intent** in the Developer Portal.
2. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`. Do not send or commit this token.
3. Install dependencies and start the bot:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe main.py
   ```

4. Invite the bot with the `bot` and `applications.commands` scopes. Give it **Manage Roles**, **Manage Nicknames**, **Send Messages**, and **Embed Links**. Its Discord role must sit above every role it needs to assign.
5. While building, set `DISCORD_GUILD_ID` to your test-server ID for immediate slash-command updates. Remove it when you are ready for global commands.

The bot creates `data/bot.sqlite3` on first start. It contains verification,
shift, and promotion history; back it up if those records matter to you.

### If command sync says “Missing Access”

`DISCORD_GUILD_ID` must be the **server ID**, not the application/client ID.
The bot must also be installed in that exact server from the same Discord
application. Reinstall it using the Developer Portal OAuth2 URL Generator with
both `bot` and `applications.commands` selected, then start the bot again.

If you do not need a development server, leave `DISCORD_GUILD_ID` blank. The
bot will sync commands globally instead; Discord can take a little while to
show global command changes.

## Interactive member panels

Once the bot is online, a staff member can deploy the panels in the channels you
choose:

```text
/panel verification #verification
/panel shift #shift-centre
```

The verification panel gives members a **Verify / Update** button. It opens a
private username form and runs the same group check, role mapping, and nickname
sync as `/verify`.

The shift panel has **Start shift**, **End shift**, and **Refresh** buttons. It
shows everyone currently on shift plus a live relative timer, refreshes after
each shift action, and updates automatically every minute. Both panel button
sets survive a bot restart. Staff can run `/panel status` to find the deployed
messages, or rerun a deployment command in the same channel to refresh one.

## Fixed information embeds and links

Edit [content/server_content.json](content/server_content.json) to maintain
your server's reusable information posts. Every entry has a unique key, a title,
description, optional fields, a default `channel_id`, and up to five HTTPS link
buttons. For example:

```json
"rules": {
  "channel_id": 123456789012345678,
  "title": "Server Rules",
  "description": "Read these before playing.",
  "colour": "#5865F2",
  "fields": [{"name": "Rule 1", "value": "Be respectful.", "inline": false}],
  "links": [{"label": "Full Rules", "url": "https://example.com/rules"}]
}
```

After saving the file, run `/content reload`. Staff can use `/content list` to
see available keys and `/content publish rules` to post a configured message;
they may choose a different target channel in the command when needed. This is
useful for rules, staff handbooks, application guides, training resources, and
ER:LC server links without editing bot code.

## Enable Roblox features when your group exists

Set `ROBLOX_GROUP_ID` to the numeric Roblox group ID. Verification then works
with Roblox's public APIs; each person runs `/verify their_username`.

For promotions, create an Open Cloud API key scoped to the group with
`group:write`, add it as `ROBLOX_OPEN_CLOUD_API_KEY`, and set an allow-list such
as:

```env
ROBLOX_PROMOTION_ROLES_JSON={"Cadet":"123456","Deputy":"123457","Corporal":"123458"}
```

Staff would then run `/promotion promote @Member Deputy reason:Completed FTO`.
The bot sends the key only to Roblox's Open Cloud endpoint and never uses a
`.ROBLOSECURITY` cookie. Roblox will still enforce the key owner's own group
hierarchy, so it cannot grant a role at or above that owner.

`ROBLOX_REPLACE_PROMOTION_ROLE` is `false` by default because Roblox groups can
now give a member multiple roles. Turn it on only if your community has one
exclusive rank per member and you want the previous highest group role removed.

## Role, nickname, and log configuration

All values below are in `.env`; use numeric IDs with Developer Mode enabled in
Discord.

```env
# Roblox group-role ID → Discord role ID
ROBLOX_ROLE_MAP_JSON={"123456":"987654321012345678","123457":"987654321012345679"}
VERIFIED_ROLE_ID=987654321012345680
NICKNAME_TEMPLATE=[{group_role}] {roblox_name}

# Staff role IDs, separated by commas. Manage Server/Administrator always work too.
STAFF_ROLE_IDS=987654321012345681,987654321012345682

# Category → Discord channel ID; omit categories you do not want logged.
LOG_CHANNELS_JSON={"verification":"111111111111111111","shift":"222222222222222222","promotion":"333333333333333333","moderation":"444444444444444444","member":"555555555555555555","admin":"666666666666666666"}
```

Available nickname fields are `{roblox_name}`, `{roblox_id}`, `{group_role}`, and
`{group_rank}`. Discord limits nicknames to 32 characters, so longer rendered
names are automatically shortened.

## Commands

- `/verify`, `/verify-sync`, `/verify-status`
- `/embed` — staff only
- `/panel verification`, `/panel shift`, `/panel status` — staff only
- `/content list`, `/content publish`, `/content reload` — staff only
- `/shift start`, `/shift end`, `/shift status`, `/shift history`, `/shift active`
- `/promotion promote`, `/promotion history` — staff only
- `/server stats`, `/server member`

## Validation

Run the built-in storage tests and syntax check before deployment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q main.py src
```

Roblox's group endpoints are currently labelled beta by Roblox, so retain the
promotion audit log and verify the result in Roblox after role changes.
