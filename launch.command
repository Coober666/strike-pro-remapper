#!/bin/bash
# Double-click this file to launch the Strike Pro Remapper.
#
# Note: if the Terminal window shows "no such file or directory: Users/..."
# (missing leading /), an oh-my-zsh update prompt consumed the first
# character of the path BEFORE this script ever ran — that failure is
# outside this script's control. Just run it again (or update oh-my-zsh).
# See README "First-run notes".
set -u
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found on this Mac."
  echo "Install it from https://www.python.org/downloads/ (or: xcode-select --install),"
  echo "then double-click this file again."
  read -r -n 1 -p "Press any key to close..."
  exit 1
fi

# stdin redirected so nothing downstream can hang on interactive input
python3 strike_remap.py </dev/null
status=$?
if [ $status -ne 0 ]; then
  echo ""
  echo "Strike Pro Remapper exited with an error (code $status) — see the messages above."
  read -r -n 1 -p "Press any key to close..."
fi
exit $status
