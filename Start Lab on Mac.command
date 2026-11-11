#!/bin/bash
# Start here on a Mac. This only opens the lab's real launcher, in the agent folder next to this file.
# It is plain text, so you can read both files before you run them.
cd -- "$(dirname -- "$0")/agent" || { echo "The agent folder is missing. Download the lab again."; exit 1; }
exec bash "./Start Lab Helper.command"
