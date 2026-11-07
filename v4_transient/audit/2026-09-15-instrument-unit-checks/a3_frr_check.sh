#!/bin/sh
# Amendment A3 instrument check with the production commands (labops.MON_CMD / SNAPSHOT_SH / POLL_SH), the pilot FRR
# image and daemons file, in ONE throwaway container (network none; no containerlab, no pilot artifact, no pilot
# change measured). Exercises: ECMP nexthop group, single-path route with backup, static blackhole override,
# vtysh `shutdown` (admin down, silent kernel flush) and peer carrier loss. Host-side epoch timestamps bracket every
# dump, as the runner's time.time() does.
N=v4audit-a3
A=/mnt/c/Users/karth/network-research-lab/v4_transient/pilot/artifacts/golden-t05_ring6/artifact/devices/corea
MON_CMD="ip -ts monitor link route nexthop"
SNAP="ip -4 route show table main; echo @@LINKS@@; ip -o link show; echo @@NEXTHOPS@@; ip nexthop show 2>/dev/null; true"
POLL="cat /tmp/v4mon.log; echo; echo @@ROUTES@@; $SNAP"
docker rm -f $N >/dev/null 2>&1
docker run -d --name $N --network none --cap-add NET_ADMIN --cap-add NET_RAW --cap-add SYS_ADMIN \
  -v $A/daemons:/etc/frr/daemons:ro frrouting/frr:v8.4.1 >/dev/null || { echo "RUN FAILED"; exit 1; }
sleep 6
X="docker exec $N"
$X sh -c 'ip link add v0 type veth peer name v1; ip link add w0 type veth peer name w1;
          ip addr add 10.9.0.1/30 dev v0; ip addr add 10.9.1.1/30 dev w0;
          for d in v0 v1 w0 w1; do ip link set $d up; done'
sleep 2
$X vtysh -c "configure terminal" -c "ip route 10.7.0.0/24 10.9.0.2" -c "ip route 10.7.0.0/24 10.9.1.2" \
   -c "ip route 10.8.0.0/24 10.9.0.2" -c "ip route 10.8.0.0/24 10.9.1.2 50" -c "ip route 10.255.0.1/32 10.9.0.2 110" >/dev/null 2>&1
sleep 3
$X sh -c ': > /tmp/v4mon.log'
docker exec -d $N sh -c "exec $MON_CMD >> /tmp/v4mon.log 2>&1"
sleep 1
dump() { echo "== $1 $(date +%s.%N)"; $X sh -c "$2"; echo "== END_$1 $(date +%s.%N)"; }
dump SNAP0 "$SNAP"
$X vtysh -c "configure terminal" -c "ip route 10.255.0.1/32 blackhole" >/dev/null 2>&1
sleep 2
dump POLL1 "$POLL"
$X vtysh -c "configure terminal" -c "interface v0" -c "shutdown" -c "exit" >/dev/null 2>&1
sleep 3
dump POLL2 "$POLL"
$X ip link set w1 down
sleep 3
dump POLL3 "$POLL"
dump FINAL "$SNAP"
echo "== MONITOR 0"; $X cat /tmp/v4mon.log; echo "== END_MONITOR 0"
docker rm -f $N >/dev/null 2>&1
