#!/bin/sh
# Instrument unit check with the pilot's FRR image and daemons file, in ONE throwaway container (network none,
# no containerlab, no pilot artifact deployed, no measurement of any pilot change). Checks exactly what the V4
# FIB instrument sees for (a) a static blackhole (population mechanism "bh") and (b) interface shutdown
# (positive-control mechanism), using the production commands: `ip -ts monitor route` and
# `ip -4 route show table main`.
N=v4audit-frr-unit
A=/mnt/c/Users/karth/network-research-lab/v4_transient/pilot/artifacts/golden-t05_ring6/artifact/devices/corea
docker rm -f $N >/dev/null 2>&1
docker run -d --name $N --network none --cap-add NET_ADMIN --cap-add NET_RAW --cap-add SYS_ADMIN \
  -v $A/daemons:/etc/frr/daemons:ro frrouting/frr:v8.4.1 >/dev/null || { echo "RUN FAILED"; exit 1; }
sleep 6
X="docker exec $N"
$X sh -c 'ip link add v0 type veth peer name v1; ip link add w0 type veth peer name w1;
          ip addr add 10.9.0.1/30 dev v0; ip addr add 10.9.1.1/30 dev w0;
          for d in v0 v1 w0 w1; do ip link set $d up; done'
sleep 2
$X vtysh -c "configure terminal" -c "ip route 10.8.0.0/24 10.9.0.2" -c "ip route 10.8.0.0/24 10.9.1.2 50" \
         -c "ip route 10.7.0.0/24 10.9.0.2" -c "ip route 10.255.0.1/32 10.9.0.2"
sleep 2
$X sh -c ': > /tmp/v4mon.log'
docker exec -d $N sh -c 'exec ip -ts monitor route >> /tmp/v4mon.log 2>&1'
sleep 1
echo "== T_BEFORE"; $X date +%s.%N
echo "== SNAP0"; $X ip -4 route show table main
$X vtysh -c "configure terminal" -c "ip route 10.255.0.1/32 blackhole"
sleep 2
echo "== SNAP1_AFTER_BLACKHOLE"; $X ip -4 route show table main
$X vtysh -c "configure terminal" -c "interface v0" -c "shutdown" -c "exit"
sleep 3
echo "== SNAP2_AFTER_SHUTDOWN"; $X ip -4 route show table main
echo "== ZEBRA"; $X vtysh -c "show ip route" | tail -8
echo "== MONITOR"; $X cat /tmp/v4mon.log
echo "== END"
docker rm -f $N >/dev/null 2>&1
