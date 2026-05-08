# ClaudeSkills

Claude Code skill files for Blender addon development.
Import these into Claude Code → Skills to use them on any computer.

## Skills

### `blender-mcp-setup`
Connects Claude to Blender via a TCP socket on port 9876 (Blender Lab extension).
Configures and verifies that `install.py` can auto-reload your addon inside Blender without manual steps.
**Trigger:** `/blender-mcp-setup` — run this first on any new computer before addon development.

### `blender-addon-init`
Scaffolds a complete new Blender addon from scratch — file structure, `__init__.py`, properties, panels,
infos operators, git with whitelist `.gitignore`, `install.py` with MCP auto-reload, and IDE setup.
**Trigger:** `/blender-addon-init`

### `blender-addon-modules`
Adds or removes feature modules inside an existing addon built with `blender-addon-init`.
Generates the module folder, operators, UI panel, local/global properties, toggle button,
and wires everything into the module manager automatically.
**Trigger:** `/blender-addon-modules add` or `/blender-addon-modules remove`

## Install on a new computer

1. Pull this repo
2. Open Claude Code → **Skills** (left sidebar)
3. Click `+` → pick a `.skill` file from this folder
4. Repeat for all 3 skills
5. Run `/blender-mcp-setup` first to verify Blender connection

## Update a skill

1. Ask Claude to update the skill — it will repackage a new `.skill` file
2. Skills UI → `...` → **Replace** → pick the new file
3. Copy the updated `.skill` back into this folder
4. Commit and push so all computers stay in sync
