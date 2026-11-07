#!/usr/bin/env python3
import csv
from collections import Counter

s = list(csv.DictReader(open('data/pilot-v2/phase3/containerlab_summary.csv')))
goldens = [x for x in s if 'golden' in x['kind']]

print('Golden runs in summary:')
print('  Total:', len(goldens))
print()
print('Sample golden rows (with key fields):')
for g in goldens[:5]:
    print(f"  {g['run_id']}: topology={g.get('topology', 'N/A')}, G_size={g.get('property_G_size', 'N/A')}")

print()
print('All golden topologies:')
topo_g = Counter()
for g in goldens:
    topo_g[g.get('topology', 'N/A')] += 1

for topo in sorted(topo_g.keys()):
    print(f'  {topo}: {topo_g[topo]} goldens')

print()
print('Golden property G sizes:')
g_sizes = Counter(g.get('property_G_size', 'N/A') for g in goldens)
for size in sorted(g_sizes.keys()):
    print(f'  G_size={size}: {g_sizes[size]} goldens')
