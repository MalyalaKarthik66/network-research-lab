#!/bin/sh
# Unit check of Linux netlink behaviour on link down, inside a throwaway container (local FRR image, no lab,
# no network download). Question: does `ip -ts monitor route` report routes the kernel flushes on link down?
docker run --rm --cap-add NET_ADMIN --network none --entrypoint sh frrouting/frr:v8.4.1 -c '
ip link add v0 type veth peer name v1
ip link add w0 type veth peer name w1
ip addr add 10.9.0.1/30 dev v0
ip addr add 10.9.1.1/30 dev w0
for d in v0 v1 w0 w1; do ip link set $d up; done
sleep 1
ip route add 10.8.0.0/24 via 10.9.0.2 proto ospf metric 20
ip route add 10.6.0.0/24 via 10.9.1.2 proto ospf metric 20
ip route add 10.7.0.0/24 proto ospf metric 20 nexthop via 10.9.0.2 dev v0 nexthop via 10.9.1.2 dev w0
(ip -ts monitor link route > /tmp/m 2>&1 &)
sleep 1
echo "== BEFORE"; ip -4 route show table main
ip link set v0 down
sleep 1
echo "== AFTER admin down v0"; ip -4 route show table main
ip link set w1 down
sleep 1
echo "== AFTER carrier loss on w0 (peer w1 down)"; ip -4 route show table main
sleep 1
echo "== MONITOR OUTPUT"; cat /tmp/m
'
