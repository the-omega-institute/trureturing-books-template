"""Advisory browser execution costs; parent impact selection remains authoritative."""
from __future__ import annotations

import hashlib
import json
import math
import re

PARTS_SCHEMA = 'tbook-viz-parts-v1'
REPORT_SCHEMA = 'tbook-viz-report-v1'
TARGET = 900
CEILING = 1200
RESERVE = 120
MARGIN = 1.25
MATRIX_LIMIT = 256
PART = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


def parts(data, suites):
    if not isinstance(data, dict) or set(data) != {'schema', 'suites'} or data['schema'] != PARTS_SCHEMA or not isinstance(data['suites'], dict):
        raise ValueError('invalid execution-parts.json schema')
    result = {}
    for name, values in data['suites'].items():
        if name not in suites or not isinstance(values, list) or not values or len(values) > 64 or any(not isinstance(x, str) or not PART.fullmatch(x) for x in values) or len(set(values)) != len(values):
            raise ValueError(f'invalid execution parts for {name}')
        result[name] = values
    return result


def units(suite, declared):
    return [suite + '#' + part for part in declared] if declared else [suite]


def fingerprint(files, declaration):
    return hashlib.sha256(json.dumps([declaration, sorted(files)], separators=(',', ':')).encode()).hexdigest()


def valid_hint(value, source):
    return (isinstance(value, dict) and value.get('source') == source and
            type(value.get('seconds')) in (int, float) and math.isfinite(value['seconds']) and
            0 < value['seconds'] <= 86400)


def pack(execution, hints, workloads=None):
    """LPT, increasing bin count to the target; unknown units run alone.

    An indivisible over-target unit is surfaced, never discarded or timed out to
    manufacture coverage. The ceiling is a rollout check, not a duration guarantee.
    """
    known, unknown = [], []
    for unit, source in sorted(execution.items()):
        hint = hints.get(unit)
        if valid_hint(hint, source):
            known.append((unit, hint['seconds'] * MARGIN))
        else:
            unknown.append(unit)
    if len(unknown) + bool(known) > MATRIX_LIMIT:
        raise ValueError('browser execution exceeds the 256-job matrix limit; decompose the workflow')
    known.sort(key=lambda pair: (-pair[1], pair[0]))
    bins = []
    if known:
        start = min(len(known), max(1, math.ceil(sum(c for _, c in known) / (TARGET - RESERVE))))
        limit = min(len(known), MATRIX_LIMIT - len(unknown))
        for count in range(min(start, limit), limit + 1):
            bins = [dict(items=[], cost=0.0) for _ in range(count)]
            for unit, cost in known:
                slot = min(range(count), key=lambda i: (bins[i]['cost'], i))
                bins[slot]['items'].append(unit)
                bins[slot]['cost'] += cost
            # More bins cannot fix an oversized indivisible unit.
            if all(b['cost'] + RESERVE <= TARGET or len(b['items']) == 1 for b in bins):
                break
        if any(len(b['items']) > 1 and b['cost'] + RESERVE > TARGET for b in bins):
            raise ValueError('browser packing cannot fit target within the matrix limit')
    rows = [dict(items=sorted(b['items']), estimated_seconds=round(b['cost'] + RESERVE, 3)) for b in bins if b['items']]
    rows += [dict(items=[unit], estimated_seconds=None) for unit in unknown]
    for i, row in enumerate(rows):
        row.update(changed_workloads=sorted(u for u in row['items'] if valid_hint(hints.get(u), execution[u]) and workloads is not None and
                                           hints[u].get('workload') != workloads[u]),
                   shard=f'{i + 1}/{len(rows)}', batch=str(i + 1),
                   budget='unknown' if row['estimated_seconds'] is None else
                   'ceiling-exceeded' if row['estimated_seconds'] >= CEILING else
                   'target-exceeded' if row['estimated_seconds'] > TARGET else 'target')
    return rows


def merge_reports(plan, reports):
    """Require exact successful current-run units before any parent coverage advances."""
    expected = plan.get('execution', {})
    seen = {p: {} for p in expected}
    for report in reports:
        profile = report.get('profile')
        if (report.get('schema') != REPORT_SCHEMA or profile not in expected or
                report.get('sha') != plan['sha'] or report.get('run_id') != plan['coverage'][profile]['run_id'] or
                report.get('run_attempt') != plan['coverage'][profile]['run_attempt'] or
                report.get('frames') != (1000 if profile == 'slow' else 0) or
                report.get('runtime') != plan['coverage'][profile]['runtime'] or not isinstance(report.get('results'), list)):
            raise ValueError('incompatible browser execution report')
        for row in report['results']:
            unit = row.get('unit')
            if unit not in expected[profile] or unit in seen[profile]:
                raise ValueError('unknown or duplicate browser execution result')
            source = expected[profile][unit]
            if type(row.get('exit_code')) is not int or row['exit_code'] != 0 or row.get('signal') is not None or not valid_hint(dict(source=source, seconds=row.get('seconds')), source):
                raise ValueError(f'failed or malformed browser execution result: {unit}')
            seen[profile][unit] = dict(source=source, seconds=row['seconds'],
                workload=plan.get('workloads', {}).get(profile, {}).get(unit, source),
                sha=report['sha'], run_id=report['run_id'], run_attempt=report['run_attempt'], node=report.get('node'))
    for profile, execution in expected.items():
        if set(seen[profile]) != set(execution):
            raise ValueError(f'missing browser execution results: {profile}')
        plan['coverage'][profile].setdefault('timings', {}).update(seen[profile])
