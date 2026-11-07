#!/bin/sh
# Instrument unit check (population mechanism "bh"): a static /32 blackhole overriding a distance-110 route,
# as ospfd's route is overridden in the lab. One throwaway container, network none, pilot image + daemons file.
N=v4audit-frr-unit2
A=/mnt/c/Users/karth/network-research-lab/v4_transient/pilot/artifacts/golden-t05_ring6/artifact/devices/corea
docker rm -f $N >/dev/null 2>&1
docker run -d --name $N --network none --cap-add NET_ADMIN --cap-add NET_RAW --cap-add SYS_ADMIN \
  -v $A/daemons:/etc/frr/daemons:ro frrouting/frr:v8.4.1 >/dev/null || { echo "RUN FAILED"; exit 1; }
sleep 6
X="docker exec $N"
$X sh -c 'ip link add v0 type veth peer name v1; ip addr add 10.9.0.1/30 dev v0; ip link set v0 up; ip link set v1 up'
sleep 2
$X vtysh -c "configure terminal" -c "ip route 10.255.0.1/32 10.9.0.2 110" >/dev/null 2>&1
sleep 2
$X sh -c ': > /tmp/v4mon.log'
docker exec -d $N sh -c 'exec ip -ts monitor route >> /tmp/v4mon.log 2>&1'
sleep 2
echo "== T_BEFORE"; $X date +%s
sleep 1
echo "== SNAP0"; $X ip -4 route show table main
$X vtysh -c "configure terminal" -c "ip route 10.255.0.1/32 blackhole" >/dev/null 2>&1
sleep 2
echo "== SNAP1_AFTER_BLACKHOLE"; $X ip -4 route show table main
echo "== SNAP2_AFTER_SHUTDOWN"; $X ip -4 route show table main
echo "== ZEBRA"; $X vtysh -c "show ip route 10.255.0.1/32" 2>/dev/null
echo "== MONITOR"; $X cat /tmp/v4mon.log
echo "== END"
docker rm -f $N >/dev/null 2>&1
