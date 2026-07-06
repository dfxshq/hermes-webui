# Canvas Integration Recovery

After a `git pull` from upstream (nesquena/hermes-webui), the custom canvas split-pane changes to `static/index.html`, `static/style.css`, and `static/panels.js` may be overwritten or stashed by the auto-update.

## Recovery

```bash
cd ~/hermes-webui

# Check if changes were stashed
git stash list | grep hermes-update-autostash

# If stashed, pop them
git stash pop

# If overwritten, pull from the dfxshq fork
git fetch fork
git cherry-pick de9388cb  # Canvas split-pane commit

# Restart the WebUI
systemctl --user restart hermes-webui.service
```

## Files Changed
- `static/index.html` — 4 additions: rail button, mobile nav button, sidebar panel (#panelCanvas), canvas pane + resize handle
- `static/style.css` — Canvas split-pane CSS rules (17 selectors) at end of file
- `static/panels.js` — Canvas toggle/open/close/resize/API/polling functions appended at end

## Canvas Commit
Commit: `de9388cb` on branch `master` at `dfxshq/hermes-webui`
