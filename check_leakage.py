#!/usr/bin/env python3
import csv
from collections import Counter

print('='*70)
print('LEAKAGE SAFEGUARDS CHECK')
print('='*70)
print()

# Load outcomes to check for banned columns
outcomes = list(csv.DictReader(open('data/pilot-v2/phase3/containerlab_outcomes.csv')))

print('1. BANNED COLUMNS IN OUTCOMES (must be empty):')
banned = ['fault_family', 'repair_id', 'repair_class', 'incident_id', 'candidate_id']
for col in banned:
    if col in outcomes[0]:
        print(f'   {col}: PRESENT in schema - must review')
    else:
        print(f'   {col}: not in outcomes (correct)')

print()
print('2. OUTCOMES CSV COLUMNS:')
print('   ', ', '.join(list(outcomes[0].keys())))

print()
print('3. INCIDENT GROUPING VERIFICATION:')
incident_counts = Counter(o['incident_id'] for o in outcomes if o['outcome_harm_v1'] in ['SAFE', 'HARMFUL'])
print(f'   Candidates per incident (n={len(outcomes)} total candidates):')
inc_dist = Counter(incident_counts.values())
for count in sorted(inc_dist.keys()):
    print(f'     {count} candidates: {inc_dist[count]} incidents')

print()
print('4. TOPOLOGY COVERAGE:')
# Infer topology from incident_id if possible, or check manifest
from pathlib import Path
import json
manifest = json.loads(Path('data/pilot-v2/manifest.json').read_text())
incidents_by_topo = {}
for inc in manifest['incidents']:
    topo = inc['topology']
    if topo not in incidents_by_topo:
        incidents_by_topo[topo] = []
    incidents_by_topo[topo].append(inc['incident_id'])

# Check if candidates span all topologies
candidate_incidents = set(o['incident_id'] for o in outcomes)
topo_coverage = {}
for topo, incs in incidents_by_topo.items():
    covered = len([inc for inc in incs if inc in candidate_incidents])
    topo_coverage[topo] = covered > 0

covered_topos = sum(1 for v in topo_coverage.values() if v)
print(f'   Topologies covered by candidates: {covered_topos}/{len(topo_coverage)}')
for topo in sorted(topo_coverage.keys()):
    status = '✓' if topo_coverage[topo] else '✗'
    print(f'     {status} {topo}')

print()
print('5. OUTCOME DISTRIBUTION BY INCIDENT FAMILY:')
# Get a sample of incident to family mapping
inc_to_family = {}
for inc in manifest['incidents']:
    inc_to_family[inc['incident_id']] = inc.get('fault_family', 'unknown')

family_dist = Counter()
for o in outcomes:
    if o['outcome_harm_v1'] in ['SAFE', 'HARMFUL']:
        family = inc_to_family.get(o['incident_id'], 'unknown')
        family_dist[family] += 1

print(f'   Total candidates with decidable outcomes: {sum(family_dist.values())}')
for family in sorted(family_dist.keys()):
    print(f'     {family}: {family_dist[family]}')

print()
print('='*70)
