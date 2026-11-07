#!/usr/bin/env bash
# V4 transient pilot: measurement-tool capability probe. Read-only; starts throwaway containers only.
set -u
echo "== FRR image frrouting/frr:v8.4.1 =="
docker run --rm --cap-add NET_ADMIN --entrypoint sh frrouting/frr:v8.4.1 -c '
ip -V
(ip -ts monitor route > /tmp/mon.txt 2>&1 &) ; sleep 0.3
ip link add dummy0 type dummy 2>/dev/null && ip link set dummy0 up && ip route add 10.99.0.0/24 dev dummy0 && ip route replace 10.99.0.0/24 dev dummy0 metric 5
sleep 0.3; echo "--- monitor output:"; cat /tmp/mon.txt
echo "--- date %N:"; date +%s.%N; date +%s%N
a=$(date +%s%N); sleep 0.05; b=$(date +%s%N); echo "sleep0.05_ns=$((b-a))"
echo "--- ip route show (kernel FIB format):"; ip -4 route show
echo "--- tools:"; for t in vtysh fping hping3 tcpdump nc timeout awk; do printf "%s=" $t; command -v $t || echo MISSING; done
busybox 2>&1 | head -1
echo "--- ping fractional:"; ping -c 5 -i 0.05 -W 1 127.0.0.1 2>&1 | tail -3
'
echo "== host image alpine:3.19 =="
docker run --rm alpine:3.19 sh -c '
a=$(date +%s%N); sleep 0.02; b=$(date +%s%N); echo "sleep0.02_ns=$((b-a))"
echo "--- ping fractional:"; ping -c 5 -i 0.05 -W 1 127.0.0.1 2>&1 | tail -3
ping -c 1 -W 1 127.0.0.1 >/dev/null 2>&1; echo ping_rc=$?
'
echo "== host =="; nproc; uname -r; containerlab version | grep -i version; docker version --format "{{.Server.Version}}"
