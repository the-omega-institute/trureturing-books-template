"""Execution units preserve selected parents; costs never stand in for coverage."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import unittest

from ci import viz_budget as budget
from test_ci_performance import planner
import test_ci_performance as fixtures


class BudgetTest(unittest.TestCase):
    def test_heterogeneous_selected_sets_are_exact_and_deterministic_without_eight_cap(self):
        for size in (0, 1, 3, 8, 19, 62):
            execution = {f'suite-{i}': 'src' for i in range(size)}
            hints = {u: dict(source='src', seconds=170 + (i % 4) * 80) for i, u in enumerate(execution)}
            rows = budget.pack(execution, hints)
            self.assertEqual(rows, budget.pack(dict(reversed(list(execution.items()))), hints))
            flat = [u for row in rows for u in row['items']]
            self.assertCountEqual(flat, execution)
            self.assertEqual(len(set(flat)), len(flat))
            self.assertTrue(all(row['items'] and row['estimated_seconds'] <= 900 for row in rows))
            if size == 62:
                self.assertGreater(len(rows), 8)
        subset = {'suite-4': 'src', 'suite-9': 'src'}
        self.assertEqual({u for r in budget.pack(subset, hints) for u in r['items']}, set(subset))

    def test_unknown_changed_bad_and_oversized_costs_do_not_drop_units(self):
        bad = [None, {}, {'source': 'old', 'seconds': 50}, {'source': 'src', 'seconds': -1},
               {'source': 'src', 'seconds': float('nan')}, {'source': 'src', 'seconds': True},
               {'source': 'src', 'seconds': '12'}, {'source': 'src', 'seconds': 999999}]
        for value in bad:
            rows = budget.pack({'new#one': 'src', 'new#two': 'src'}, {'new#one': value}, {'new#one': 'work', 'new#two': 'work'})
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(len(r['items']) == 1 and r['budget'] == 'unknown' for r in rows))
        rows = budget.pack({'large': 'src', 'small': 'src'}, {
            'large': dict(source='src', seconds=1000), 'small': dict(source='src', seconds=1)})
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['budget'], 'ceiling-exceeded')
        with self.assertRaisesRegex(ValueError, '256'):
            budget.pack({str(i): 'src' for i in range(257)}, {})
        self.assertEqual(budget.pack({}, {'removed': dict(source='src', seconds=100)}), [])

    def test_part_contract_rejects_empty_duplicate_unsafe_unknown_and_excessive_parts(self):
        for values in ([], ['a', 'a'], ['../a'], [1], ['a'] * 65):
            with self.assertRaises(ValueError):
                budget.parts(dict(schema=budget.PARTS_SCHEMA, suites={'a.test.mjs': values}), ['a.test.mjs'])
        with self.assertRaises(ValueError):
            budget.parts(dict(schema=budget.PARTS_SCHEMA, suites={'gone.test.mjs': ['a']}), ['a.test.mjs'])
        self.assertEqual(budget.units('owner', ['a', 'b']), ['owner#a', 'owner#b'])
        self.assertEqual(budget.units('owner', []), ['owner'])

    def fixture(self):
        return dict(sha='head', execution={'normal': {'owner#a': 'src', 'owner#b': 'src'}, 'slow': {}},
                    coverage={p: dict(run_id='7', run_attempt='2', runtime={'image': 'one'}, timings={}) for p in ('normal', 'slow')})

    def report(self):
        return dict(schema=budget.REPORT_SCHEMA, sha='head', run_id='7', run_attempt='2', runtime={'image': 'one'},
                    frames=0, profile='normal', results=[dict(unit=f'owner#{p}', seconds=3, exit_code=0, signal=None) for p in ('a', 'b')])

    def test_reports_require_exact_successful_units_profile_runtime_and_run_attempt(self):
        plan, report = self.fixture(), self.report()
        budget.merge_reports(plan, [report])
        self.assertEqual(set(plan['coverage']['normal']['timings']), {'owner#a', 'owner#b'})
        changes = [dict(sha='wrong'), dict(run_id='8'), dict(run_attempt='1'), dict(frames=1000),
                   dict(profile='slow'), dict(runtime={'image': 'two'}), dict(schema='old'),
                   dict(results=report['results'][:1]), dict(results=report['results'] * 2)]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                budget.merge_reports(self.fixture(), [dict(report, **change)])
        for change in (dict(exit_code=1), dict(exit_code=False), dict(signal='SIGTERM'), dict(seconds=0), dict(unit='gone')):
            bad = copy.deepcopy(report); bad['results'][0].update(change)
            with self.assertRaises(ValueError):
                budget.merge_reports(self.fixture(), [bad])
        with self.assertRaises(ValueError):
            budget.merge_reports(self.fixture(), [])
        budget.merge_reports(dict(execution={}, coverage={}), [])


class ParentIntegrationTest(unittest.TestCase):
    setUp = fixtures.AffectedPlanTest.setUp
    git = fixtures.AffectedPlanTest.git
    write = fixtures.AffectedPlanTest.write
    commit = fixtures.AffectedPlanTest.commit
    impact = fixtures.AffectedPlanTest.impact
    make_plan = fixtures.AffectedPlanTest.make_plan

    def test_changed_metadata_selects_only_owner_and_all_parts_after_parent_selection(self):
        self.write('books/one/viz/tests/execution-parts.json', json.dumps(dict(schema=budget.PARTS_SCHEMA, suites={'a.test.mjs': ['first', 'second']})))
        self.commit()
        plan = self.make_plan()
        owner = 'books/one/viz/tests/a.test.mjs'
        self.assertEqual(plan['selections']['normal']['suites'], [owner])
        self.assertEqual(set(plan['execution']['normal']), {owner + '#first', owner + '#second'})
        self.assertEqual(len(plan['viz']), 2)
        # Unrelated documentation preserves empty selection despite parts being present.
        self.base = self.git('rev-parse', 'HEAD')
        self.write('docs/unrelated.md', 'note'); self.commit()
        self.assertEqual(self.make_plan()['viz'], [])
        self.write('books/one/viz/tests/execution-parts.json', json.dumps(dict(schema=budget.PARTS_SCHEMA, suites={})))
        self.commit()
        self.assertEqual(set(self.make_plan()['execution']['normal']), {owner})

    def test_imported_helper_and_real_workload_changes_invalidate_only_own_cost(self):
        owner = 'books/one/viz/tests/a.test.mjs'
        self.write(owner, 'import "./helper.mjs";\n')
        self.write('books/one/viz/tests/helper.mjs', 'export const a=1;')
        self.commit()
        before = planner.execution_inventory(planner.Tree(self.root, 'HEAD'))
        self.write('books/one/viz/tests/helper.mjs', 'export const a=2;'); self.commit()
        after = planner.execution_inventory(planner.Tree(self.root, 'HEAD'))
        self.assertNotEqual(before[owner], after[owner])
        other = 'books/two/viz/tests/b.test.mjs'
        self.assertEqual(before[other], after[other])
        self.assertEqual(self.impact()['suites'], [owner])

    def test_trusted_costs_are_advisory_pr_profile_separation_and_removed_hint_pruning(self):
        self.write('books/one/viz/a/model.js', 'changed'); self.commit()
        execution, workloads = planner.execution_inventory(planner.Tree(self.root, 'HEAD'), with_workloads=True)
        owner = 'books/one/viz/tests/a.test.mjs'
        source = execution[owner][owner]
        def get(*args):
            return dict(sha=self.base, source_run=17, artifact_id=42,
                        timings={owner: dict(source=source, workload=workloads[owner], seconds=20), 'removed': dict(source='old', seconds=1)}) if args[4] == 'normal' else dict(sha=self.base, source_run=17, artifact_id=42)
        plan = planner.plan(self.root, event='workflow_dispatch', payload={}, repo='owner/books', branch='main', ref='refs/heads/main', slow=True, get_baseline=get)
        self.assertEqual(plan['viz'][0]['budget'], 'target')
        self.assertTrue(all(r['budget'] == 'unknown' for r in plan['slow']))
        self.assertNotIn('removed', plan['coverage']['normal']['timings'])
        self.assertEqual(plan['selections']['normal']['suites'], plan['selections']['slow']['suites'])

    def test_full_mode_reuses_trusted_weights_without_inheriting_coverage_and_tags_changed_workload(self):
        before, workloads = planner.execution_inventory(planner.Tree(self.root, 'HEAD'), with_workloads=True)
        hints = {u: dict(source=src, workload=workloads[u], seconds=20) for group in before.values() for u, src in group.items()}
        owner = 'books/one/viz/tests/a.test.mjs'
        self.write('books/one/viz/a/index.html', '<p>new reader workload</p>'); self.commit()
        def get(*args):
            return dict(sha=self.base, source_run=17, artifact_id=42, timings=hints)
        options = dict(event='push', payload={}, repo='owner/books', branch='main', ref='refs/heads/main', get_baseline=get)
        full = planner.plan(self.root, mode='full', **options)
        self.assertEqual(len(full['execution']['normal']), 4)
        self.assertEqual(len(full['viz']), 1)
        self.assertIsNone(full['coverage']['normal']['inherited'])
        self.assertEqual(full['viz'][0]['changed_workloads'], [owner])
        incremental = planner.plan(self.root, **options)
        self.assertEqual(incremental['selections']['normal']['suites'], [owner])
        self.assertEqual(incremental['viz'][0]['changed_workloads'], [owner])


class ChildRunnerTest(unittest.TestCase):
    setUp = fixtures.AffectedPlanTest.setUp
    git = fixtures.AffectedPlanTest.git
    write = fixtures.AffectedPlanTest.write
    commit = fixtures.AffectedPlanTest.commit

    def run_child(self, selection, *, slow=False, fail='', inherited='poison'):
        script = Path(__file__).parents[1] / 'node/viz-test.mjs'
        report = self.root / 'report.json'; report.unlink(missing_ok=True)
        env = dict(os.environ, TBOOK_ROOT=str(self.root), CI_ITEMS=json.dumps(selection), FAIL_PART=fail, VIZ_TEST_PART=inherited)
        args = ['node', str(script), '--selection-env', 'CI_ITEMS', '--report', str(report)] + (['--slow'] if slow else [])
        run = subprocess.run(args, env=env, text=True, capture_output=True)
        return run, json.loads(report.read_text()) if report.exists() else None

    def test_real_children_exact_parts_failure_timing_and_standalone_environment(self):
        owner = 'books/one/viz/tests/a.test.mjs'
        self.write('books/one/viz/tests/execution-parts.json', json.dumps(dict(schema=budget.PARTS_SCHEMA, suites={'a.test.mjs': ['first', 'second']})))
        self.write(owner, 'console.log("PART="+process.env.VIZ_TEST_PART); process.exit(process.env.VIZ_TEST_PART === process.env.FAIL_PART ? 1 : 0);')
        run, report = self.run_child([owner + '#first', owner + '#second'], fail='second')
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual([r['exit_code'] for r in report['results']], [0, 1])
        self.assertTrue(all(r['seconds'] > 0 for r in report['results']))
        self.assertIn('PART=first', run.stdout); self.assertIn('PART=second', run.stdout)
        run, report = self.run_child([owner], slow=True, fail='never')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('PART=\n', run.stdout)
        self.assertEqual(report['frames'], 1000)
        self.assertEqual(report['profile'], 'slow')
        run, report = self.run_child([])
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(report['results'], [])
        for bad in ([owner, owner + '#first'], [owner + '#unknown'], [owner + '#first'] * 2):
            run, report = self.run_child(bad)
            self.assertNotEqual(run.returncode, 0)
            self.assertIsNone(report)

    def test_actual_check_cli_requires_every_part_even_when_job_status_says_success(self):
        import shutil
        import sys
        owner = 'books/one/viz/tests/a.test.mjs'
        self.write('books/one/viz/tests/execution-parts.json', json.dumps(dict(schema=budget.PARTS_SCHEMA, suites={'a.test.mjs': ['first', 'second']})))
        self.write(owner, 'process.exit(process.env.VIZ_TEST_PART === process.env.FAIL_PART ? 1 : 0);')
        units = [owner + '#first', owner + '#second']
        run, success = self.run_child(units, fail='never')
        self.assertEqual(run.returncode, 0, run.stderr)
        result = dict(sha=success['sha'], execution={'normal': {u: 'source' for u in units}},
                      tasks={'viz': True}, coverage={'normal': dict(run_id=success['run_id'],
                      run_attempt=success['run_attempt'], runtime=success['runtime'], inherited=None)})
        def verify(report):
            shutil.rmtree(self.root / 'coverage', ignore_errors=True)
            shutil.rmtree(self.root / 'viz-reports', ignore_errors=True)
            if report is not None:
                self.write('viz-reports/normal.json', json.dumps(report))
            return subprocess.run([sys.executable, str(Path(__file__).parents[1] / 'ci/plan.py'), '--verify'],
                cwd=self.root, env=dict(os.environ, PLAN_JSON=json.dumps(result), RESULTS_JSON=json.dumps({
                    'plan': {'result': 'success'}, 'viz': {'result': 'success'}})), capture_output=True, text=True)
        for failing in ('first', 'second'):
            run, failed = self.run_child(units, fail=failing)
            self.assertEqual(run.returncode, 1)
            check = verify(failed)
            self.assertNotEqual(check.returncode, 0)
            self.assertFalse((self.root / 'coverage').exists())
        for report in (None, dict(success, results=success['results'][:1]),
                       dict(success, results=success['results'] * 2)):
            self.assertNotEqual(verify(report).returncode, 0)
            self.assertFalse((self.root / 'coverage').exists())
        check = verify(success)
        self.assertEqual(check.returncode, 0, check.stderr)
        record = json.loads((self.root / 'coverage/normal.json').read_text())
        self.assertEqual(set(record['timings']), set(units))


if __name__ == '__main__':
    unittest.main()
