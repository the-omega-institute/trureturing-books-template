import json
import subprocess
import unittest
from unittest.mock import patch

from tbook import github


class GitHubReadTest(unittest.TestCase):
    def test_actions_retries_after_core_quota_reset(self):
        commands = [
            subprocess.CompletedProcess([], 1, '', 'API rate limit exceeded (HTTP 403)'),
            subprocess.CompletedProcess([], 0, json.dumps({'resources': {'core': {'remaining': 0, 'reset': 110}}}), ''),
            subprocess.CompletedProcess([], 0, '[[]]', ''),
        ]
        with (patch.dict(github.os.environ, {'GITHUB_ACTIONS': 'true'}),
              patch.object(github.time, 'time', return_value=100),
              patch.object(github.time, 'sleep') as sleep,
              patch.object(github.subprocess, 'run', side_effect=commands) as run):
            self.assertEqual(github.read_json('repos/owner/repo/releases', paginate=True), [[]])
        sleep.assert_called_once_with(12)
        self.assertEqual(run.call_args_list[0].args, run.call_args_list[-1].args)

    def test_pages_lookup_can_wait_for_a_reset_outside_the_default_window(self):
        limited = subprocess.CompletedProcess([], 1, '', 'API rate limit exceeded (HTTP 403)')
        quota = subprocess.CompletedProcess([], 0, json.dumps({'resources': {'core': {'remaining': 0, 'reset': 1300}}}), '')
        success = subprocess.CompletedProcess([], 0, '[]', '')
        endpoint = 'repos/owner/repo/deployments'
        with (patch.dict(github.os.environ, {'GITHUB_ACTIONS': 'true'}),
              patch.object(github.time, 'time', return_value=1000),
              patch.object(github.time, 'sleep') as sleep,
              patch.object(github.subprocess, 'run', side_effect=[limited, quota, limited, quota, success])):
            with self.assertRaises(subprocess.CalledProcessError):
                github.read_json(endpoint)
            sleep.assert_not_called()
            self.assertEqual(github.read_json(endpoint, max_rate_limit_wait=3605), [])
            sleep.assert_called_once_with(302)

    def test_other_forbidden_responses_do_not_retry(self):
        failure = subprocess.CompletedProcess([], 1, '', 'Resource not accessible (HTTP 403)')
        with (patch.dict(github.os.environ, {'GITHUB_ACTIONS': 'true'}),
              patch.object(github.time, 'sleep') as sleep,
              patch.object(github.subprocess, 'run', return_value=failure) as run):
            with self.assertRaises(subprocess.CalledProcessError):
                github.read_json('repos/owner/repo/deployments')
        sleep.assert_not_called()
        self.assertEqual(run.call_count, 1)
