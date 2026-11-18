import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]

class RecapTest(unittest.TestCase):
    def test_extract_and_exclude(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            project = home / 'my.project'
            project.mkdir()
            logs = home / '.claude/projects' / re.sub(r'[^a-zA-Z0-9-]', '-', str(project))
            logs.mkdir(parents=True)
            old = logs / 'old.jsonl'
            old.write_text(json.dumps({'type':'user','message':{'content':'old'}}) + '\n')
            new = logs / 'new.jsonl'
            rows = [{'type':'user','message':{'content':str(i)}} for i in range(35)]
            rows += [{'type':'assistant','message':{'content':[{'type':'tool_use','name':'secret'}, {'type':'text','text':'x'*900}]}}, {'type':'user','message':{'content':[{'type':'tool_result','content':'hidden'}]}}]
            new.write_text(''.join(json.dumps(x)+'\n' for x in rows))
            os.utime(old, (1,1))
            env = dict(os.environ, HOME=d)
            cmd = [str(REPO / 'bin/cao-recap'), str(project)]
            subprocess.run(cmd, env=env, check=True)
            content = (project / '.cao/last-session.md').read_text()
            self.assertIn('new', content)
            self.assertIn(str(new), content)
            self.assertNotIn('hidden', content)
            self.assertNotIn('secret', content)
            self.assertNotIn('x'*801, content)
            self.assertNotIn('\n0\n', content)
            self.assertIn('x'*800, content)
            subprocess.run(cmd + ['--exclude', 'new'], env=env, check=True)
            self.assertIn('old', (project / '.cao/last-session.md').read_text())
            (project / '.cao/last-session.md').unlink()
            subprocess.run(cmd + ['--exclude', 'old'], env=dict(env, HOME=str(home / 'empty')), check=True)
            self.assertFalse((project / '.cao/last-session.md').exists())

if __name__ == '__main__': unittest.main()
