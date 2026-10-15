#!/bin/sh
# Playwright rejects the bare NO value in launchOptions.args. Forward all of its
# normal flags unchanged, then add an AppKit preference for this process only.
set -eu
: "${STRIKE_PLAYWRIGHT_WEBKIT:?Playwright WebKit executable is required}"
exec "$STRIKE_PLAYWRIGHT_WEBKIT" "$@" -NSAutomaticWindowAnimationsEnabled NO
