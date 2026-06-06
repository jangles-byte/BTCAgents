#!/bin/bash
# BTCAgents — same as START.command (the dashboard now controls the agent loop
# and buying via its own buttons). Kept so either file works.
cd "$(dirname "$0")" || exit 1
exec ./START.command
