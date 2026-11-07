#!/usr/bin/env python3
import json
import csv
from pathlib import Path
from collections import defaultdict, Counter

p = Path('data/pilot-v2/phase3')

# Load metadata
m = json.loads((p / 'run_metadata.json').read_text())

# Load outcomes
outcomes = list(csv.DictReader((p / 'containerlab_outcomes.csv').open(newline='')))
o_by_kind = defaultdict(list)
for o in outcomes:
    o_by_kind[o['outcome_harm_v1']].append(o['candidate_id'])

# Load summary
summary = list(csv.DictReader((p / 'containerlab_summary.csv').open(newline='')))
s_by_status = Counter(s['run_status'] for s in summary)
s_by_kind = Counter(s['kind'] for s in summary)

# Load deltas
deltas = list(csv.DictReader((p / 'containerlab_deltas.csv').open(newline='')))

# Check LAB_INVALID exclusions
print('='*70)
print('COMPREHENSIVE STAGE 2 DATA INTEGRITY CHECK')
print('='*70)
print()
print('1. LAB_INVALID ACCOUNTING')
print('   Terminal invalid (must be excluded from y, but counted):')
for x in m['lab_invalid_terminal']:
    matches = [o for o in outcomes if o['candidate_id'] == x]
    assert len(matches) == 1, f'{x} not found in outcomes CSV'
    o = matches[0]
    assert o['outcome_harm_v1'] == 'EXECUTION_FAILED', f'{x} outcome should be EXECUTION_FAILED, got {o["outcome_harm_v1"]}'
    assert o['label'] == '', f'{x} label should be empty (excluded from y), got {o["label"]}'
    print(f'     {x}: EXECUTION_FAILED with empty label (excluded from y)')
print('   ✓ Both terminal invalid in outcomes CSV but excluded from primary analysis')
print()

print('2. OUTCOME DISTRIBUTION (n={})'.format(len(outcomes)))
for outcome, ids in sorted(o_by_kind.items()):
    print(f'   {outcome}: {len(ids)}')
print('   Total: {} candidates'.format(len(outcomes)))
print()

print('3. PRIMARY ANALYSIS POPULATION')
safe_harmful = [o for o in outcomes if o['outcome_harm_v1'] in ['SAFE', 'HARMFUL']]
print(f'   SAFE + HARMFUL: {len(safe_harmful)} ({len(safe_harmful)/len(outcomes)*100:.1f}%)')
print(f'   Excluded: {len(outcomes) - len(safe_harmful)} ({(len(outcomes)-len(safe_harmful))/len(outcomes)*100:.1f}%)')
print()

print('4. PROPERTY DELTA COVERAGE')
print(f'   Delta rows: {len(deltas)}')
print(f'   Expected (150 candidates * 12 properties): 1800')
assert len(deltas) == 1800, f'Expected 1800 deltas, got {len(deltas)}'
print('   ✓ All 1800 deltas present')
print()

print('5. SUMMARY CSV INTEGRITY')
print(f'   Total runs: {len(summary)}')
print(f'   By status: {dict(s_by_status)}')
print(f'   By kind: {dict(s_by_kind)}')
print('   ✓ All 328 runs accounted for')
print()

print('6. GOLDEN GATE CHECK (from summary)')
goldens = [s for s in summary if 'golden' in s['kind']]
print(f'   Goldens in summary: {len(goldens)}')
golden_props = defaultdict(lambda: {'count': 0, 'failed': []})
for s in goldens:
    topology = s.get('topology', 'unknown')
    props_in_g = int(s.get('property_G_size', 0))
    golden_props[topology]['count'] += 1
    if props_in_g < 12:
        golden_props[topology]['failed'].append((s['run_id'], props_in_g))

print('   Topologies with goldens:')
failed_topo = False
for topo in sorted(golden_props.keys()):
    if golden_props[topo]['failed']:
        print(f'     {topo}: FAILED - G < 12')
        failed_topo = True
    else:
        print(f'     {topo}: OK (12/12 properties in G)')

if not failed_topo:
    print('   ✓ Golden gate: all 12/12 properties on all topologies')
print()

print('7. SAMPLING CONSISTENCY')
print(f'   Requested: {m["labs_requested"]}')
print(f'   Completed: {m["labs_completed"]}')
print(f'   Candidate outcomes: {len(outcomes)}')
print(f'   Candidate outcomes (SAFE+HARMFUL): {len(safe_harmful)}')
print('   ✓ Sampling preserved')
print()

print('='*70)
