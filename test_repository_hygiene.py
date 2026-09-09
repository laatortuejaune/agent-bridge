"""Guard the published tree against accidental local state and personal paths."""
from pathlib import Path
import re
import subprocess
import unittest


class RepositoryHygieneTests(unittest.TestCase):
    def test_tracked_tree_contains_source_not_private_state(self):
        root=Path(__file__).resolve().parent
        result=subprocess.run(['git','-C',str(root),'ls-files','-z'],capture_output=True,check=True)
        names=[x for x in result.stdout.decode().split('\0') if x]
        self.assertTrue(names,'Run this check in the source Git checkout.')
        blocked={'verification.json','VERIFICATION.md','PLAN.md','config.json','installed.json','uninstalled.json','.claude.json'}
        for name in names:
            path=Path(name)
            self.assertFalse(set(path.parts)&{'backups','configuration-history','.claude','.codex','__pycache__','work','outputs'},name)
            self.assertNotIn(path.name,blocked)
            self.assertFalse(re.search(r'\.(?:sqlite\w*|db|log|jsonl|pyc)$',name),name)
            content=(root/path).read_text(encoding='utf-8')
            personal_paths=re.findall(r'/Users/([A-Za-z0-9_.-]+)/',content)
            self.assertTrue(all(x in {'example','test','user'} for x in personal_paths),name)
            self.assertNotRegex(content,r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',name)


if __name__=='__main__':unittest.main()
