#!/bin/sh
set -eu

# A named volume may be initialized by Docker as root. Normalize only the
# application data directory, then run the actual process unprivileged.
mkdir -p /app/data
chown -R jurix:jurix /app/data

exec gosu jurix "$@"
