#!/bin/bash
# Sync YS Guardian plugin to Cinema 4D plugins folder
cp -R "$(dirname "$0")/plugin/" "/Users/javiermelgar/Library/Preferences/Maxon/Maxon Cinema 4D 2026_9D810372/plugins/YS_Guardian/"
echo "Synced to C4D plugins folder. Restart Cinema 4D to reload."
