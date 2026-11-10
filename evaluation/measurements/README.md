# Shared measurements

Anonymous results files that people chose to share. The public Results page and the "what can my laptop run" picker are built from them.

## Adding one
1. In the lab, open **Measure** and run a measurement.
2. Press **Download JSON**. The file has no name, account or folder path in it. Open it and check you're happy to share it.
3. Send it to the team, or add it to this folder in a pull request.
4. Run `python scripts/sync_portal_data.py`, then `python scripts/check_project.py`.

The script validates every file and recomputes its numbers from the individual runs, so a file can't claim a speed its runs don't show. A file can't say who sent it, so results are grouped by kind of laptop, by chip and memory.

Only measured sessions belong here. Synthetic examples stay in `portal/examples/`.
