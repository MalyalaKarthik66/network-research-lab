#!/usr/bin/env bash
set -u
echo "batfish_from_wsl: $(curl -s -o /dev/null -w '%{http_code}' http://localhost:9996/v2/networks)"
/mnt/c/Users/karth/network-research-lab/.venv-wsl/bin/python -c 'import sys, pybatfish, pandas; print("venv-wsl", sys.version.split()[0], "pybatfish", pybatfish.__version__, "pandas", pandas.__version__)'
docker run --rm --entrypoint sh frrouting/frr:v8.4.1 -c 'echo frr_pkill=$(command -v pkill); echo frr_date="$(date)"'
docker run --rm alpine:3.19 sh -c 'echo alpine_pkill=$(command -v pkill); echo alpine_date="$(date)"'
echo "host_date_utc: $(date -u)"
