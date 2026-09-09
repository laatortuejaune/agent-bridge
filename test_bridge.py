import concurrent.futures
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from bridge import Bridge, canonical, sanitize


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.state=self.root/'state'; self.state.mkdir()
        self.home=self.root/'home';self.home.mkdir()
        (self.state/'config.json').write_text(json.dumps({'home':str(self.home)}))
        self.b=Bridge(self.state)
        self.a=str(self.root/'project-a');self.c=str(self.root/'project-b')

    def tearDown(self):
        self.b.close();self.temp.cleanup()

    def test_scope_and_global(self):
        for project,text in [(self.a,'apricot A'),(self.c,'apricot B'),('global','apricot global')]:
            self.b.put(project,'user',project,'note','fruit',text)
        rows=self.b.recall(self.a,'apricot')
        self.assertEqual({r['body'] for r in rows},{'apricot A','apricot global'})
        self.assertEqual(len(self.b.recall(self.a,'apricot',all_projects=True)),3)

    def test_update_preserves_history_and_idempotence(self):
        first=self.b.put('x','claude',self.a,'decision','DB','Use SQLite')
        again=self.b.put('x','claude',self.a,'decision','DB','Use SQLite')
        self.assertEqual(first,again)
        second=self.b.put('x','claude',self.a,'decision','DB','Use Postgres')
        self.assertNotEqual(first,second)
        self.assertEqual(len(self.b.recall(self.a)),1)
        self.assertEqual(len(self.b.recall(self.a,history=True)),2)

    def test_conflicting_agents_retained(self):
        self.b.put('a','claude',self.a,'decision','database','Use SQLite')
        self.b.put('b','codex',self.a,'decision','database','Use Postgres')
        rows=self.b.recall(self.a)
        self.assertEqual(len(rows),2)
        self.assertEqual({r['agent'] for r in rows},{'claude','codex'})

    def test_duplicate_content_keeps_both_provenances(self):
        self.b.put('a','claude',self.a,'note','same','Use SQLite')
        self.b.put('b','codex',self.a,'note','same','Use SQLite')
        rows=self.b.recall(self.a)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(rows[0]['provenance']),2)

    def test_redaction_before_storage(self):
        values=['sk-proj-'+'aB9'*20,'ghp_'+'A1b'*15,'password = hunter2','Bearer abcdef123456','hello@example.com']
        self.b.put('source','user',self.a,'note','credentials','\n'.join(values))
        row=self.b.recall(self.a)[0]
        for value in values:
            self.assertNotIn(value,row['body'])
        self.assertNotIn('hunter2',row['body'])
        self.assertIn('REMOVED',row['body'])
        self.assertNotIn('hidden',sanitize('<private>hidden</private>'))

    def test_configured_opaque_credential_redacted_without_label(self):
        value='abc123ef'*8
        (self.home/'.claude.json').write_text(json.dumps({'mcpServers':{'example':{'env':{'API_KEY':value}}}}))
        self.b.close();self.b=Bridge(self.state)
        self.b.put('note','user',self.a,'note','opaque',f'This used {value} yesterday')
        self.assertNotIn(value,self.b.recall(self.a)[0]['body'])

    def test_valid_long_local_paths_are_not_mistaken_for_credentials(self):
        path='/Users/example/Documents/Codex/2026-09-08/a-long-project-name/outputs/README.md'
        self.assertEqual(sanitize(path),path)

    def test_native_import_update_delete_no_loop(self):
        p=self.home/'.claude/projects/example/memory/fact.md';p.parent.mkdir(parents=True)
        p.write_text('---\nname: preference\nmetadata:\n  type: feedback\n---\nUse pnpm always')
        self.assertEqual(self.b.sync()['changed_files'],1)
        self.assertEqual(self.b.sync()['changed_files'],0)
        self.assertEqual(self.b.recall(self.a,'pnpm')[0]['agent'],'claude')
        p.write_text('---\nname: preference\nmetadata:\n  type: feedback\n---\nUse pnpm 11')
        self.b.sync();self.assertEqual(len(self.b.recall(self.a,'pnpm',history=True)),2)
        p.unlink();self.b.sync();self.assertEqual(self.b.recall(self.a,'pnpm'),[])
        self.assertEqual(len(self.b.recall(self.a,'pnpm',history=True)),2)

    def test_oversized_native_update_retains_last_good_version(self):
        p=self.home/'.claude/projects/example/memory/fact.md';p.parent.mkdir(parents=True)
        p.write_text('type: feedback\nOriginal useful fact');self.b.sync()
        p.write_text('type: feedback\n'+('x'*200001))
        result=self.b.sync();self.assertTrue(result['errors'])
        self.assertIn('Original useful fact',self.b.recall(self.a)[0]['body'])
        output=self.b.hook('claude','SessionStart',{'cwd':self.a,'session_id':'oversize'})
        self.assertIn('import incomplet',output['systemMessage'])

    def test_duplicate_section_titles_keep_both_current_bodies(self):
        p=self.home/'.codex/memories/MEMORY.md';p.parent.mkdir(parents=True)
        p.write_text(f'# Task Group: Same\ncwd: {self.a}\nFirst independent fact\n\n# Task Group: Same\ncwd: {self.a}\nSecond independent fact')
        self.b.sync();self.assertEqual(len(self.b.recall(self.a)),2)

    def test_raw_memories_keep_per_thread_dates_and_real_project_scope(self):
        p=self.home/'.codex/memories/raw_memories.md';p.parent.mkdir(parents=True)
        p.write_text(f'# Raw Memories\n\n## Thread `one`\nupdated_at: 2026-01-01T00:00:00Z\ncwd: /\n cwd: {self.a}\nDetailed orchard fact\n\n## Thread `two`\nupdated_at: 2026-02-01T00:00:00Z\ncwd: {self.c}\nDetailed vineyard fact')
        result=self.b.sync();self.assertFalse(result['errors'])
        a=self.b.recall(self.a);c=self.b.recall(self.c)
        self.assertEqual(len(a),1);self.assertEqual(len(c),1)
        self.assertEqual(a[0]['modified'],'2026-01-01T00:00:00Z');self.assertEqual(c[0]['modified'],'2026-02-01T00:00:00Z')
        self.assertEqual(a[0]['kind'],'native-raw')

    def test_summary_inventory_preserved_without_global_project_leak(self):
        p=self.home/'.codex/memories/memory_summary.md';p.parent.mkdir(parents=True)
        p.write_text('## User Profile\nGeneral preference\n\n## What is in Memory\nInventory-only unique detail')
        self.b.sync()
        self.assertEqual(self.b.recall(self.a,'Inventory'),[])
        self.assertEqual(len(self.b.recall(self.a,'Inventory',all_projects=True)),1)

    def test_codex_scoped_sections(self):
        p=self.home/'.codex/memories/MEMORY.md';p.parent.mkdir(parents=True)
        p.write_text(f'# Task Group: A\napplies_to: cwd={self.a}; reuse_rule=x\nApricot A\n\n# Task Group: B\napplies_to: cwd={self.c}; reuse_rule=x\nApricot B')
        self.b.sync();rows=self.b.recall(self.a,'Apricot')
        self.assertEqual(len(rows),1);self.assertNotIn('Apricot B',rows[0]['body'])

    def test_scope_reclassification_invalidates_old_active_scope(self):
        p=self.home/'.claude/projects/example/memory/fact.md';p.parent.mkdir(parents=True);p.write_text('A scoped fact')
        self.b.config['source_scopes']={str(p):self.a};self.b.sync()
        self.assertEqual(len(self.b.recall(self.a)),1)
        self.b.config['source_scopes']={str(p):self.c};self.b.sync()
        self.assertEqual(self.b.recall(self.a),[])
        self.assertEqual(len(self.b.recall(self.a,history=True)),1)
        self.assertEqual(len(self.b.recall(self.c)),1)

    def test_multi_scope_metadata_does_not_invent_directory_name(self):
        p=self.home/'.codex/memories/MEMORY.md';p.parent.mkdir(parents=True)
        p.write_text(f'# Task Group: Shared\napplies_to: cwd={self.a} and {self.c}; reuse_rule=x\nBoth projects')
        self.b.sync()
        self.assertEqual(len(self.b.recall(self.a)),1);self.assertEqual(len(self.b.recall(self.c)),1)

    def test_project_instructions_fallback_preserves_native_override(self):
        a=Path(self.a);a.mkdir();(a/'AGENTS.md').write_text('Rule: copper crane')
        out=self.b.hook('claude','SessionStart',{'cwd':str(a),'session_id':'rules'})
        self.assertIn('copper crane',out['hookSpecificOutput']['additionalContext'])
        (a/'CLAUDE.md').write_text('Claude-specific rule')
        out=self.b.hook('claude','SessionStart',{'cwd':str(a),'session_id':'rules'})
        self.assertNotIn('copper crane',out['hookSpecificOutput']['additionalContext'])

    def test_config_sync_both_directions_conflicts_and_secret_exclusion(self):
        from config_sync import sync
        c=self.home/'.claude.json';x=self.home/'.codex/config.toml';x.parent.mkdir()
        c.write_text(json.dumps({'other':'preserve','mcpServers':{'example':{'command':'python','args':['one'],'env':{'API_KEY':'secret-claude','MODE':'one','OVERRIDE':'claude'}}}}))
        x.write_text('model = "keep"\n[mcp_servers.example]\ncommand = "python"\nargs = ["one"]\n[mcp_servers.example.env]\nAPI_KEY = "secret-codex"\nMODE = "one"\nOVERRIDE = "codex"\n')
        sync(self.state,self.home,['example'])
        d=json.loads(c.read_text());d['mcpServers']['example']['args']=['two'];c.write_text(json.dumps(d))
        r=sync(self.state,self.home,['example']);self.assertEqual(len(r['edits']),1)
        self.assertIn('args = ["two"]',x.read_text())
        x.write_text(x.read_text().replace('MODE = "one"','MODE = "three"'))
        sync(self.state,self.home,['example']);self.assertEqual(json.loads(c.read_text())['mcpServers']['example']['env']['MODE'],'three')
        d=json.loads(c.read_text());d['mcpServers']['example']['command']='left';c.write_text(json.dumps(d))
        x.write_text(x.read_text().replace('command = "python"','command = "right"'))
        r=sync(self.state,self.home,['example']);self.assertTrue(r['conflicts'])
        self.assertEqual(json.loads(c.read_text())['mcpServers']['example']['command'],'left')
        self.assertIn('command = "right"',x.read_text())
        self.assertIn('secret-codex',x.read_text());self.assertIn('secret-claude',c.read_text())
        self.assertNotIn('secret-',(self.state/'configuration-state.json').read_text())
        self.assertEqual(json.loads(c.read_text())['other'],'preserve')
        self.assertIn('model = "keep"',x.read_text())
        self.assertEqual(sync(self.state,self.home,['example'])['edits'],[])

    def test_hooks_handoff_restart(self):
        base={'cwd':self.a,'session_id':'test'}
        self.b.hook('claude','UserPromptSubmit',{**base,'prompt':'Build apricot'})
        self.b.hook('claude','Stop',{**base,'last_assistant_message':'Apricot deployed; integration test pending.'})
        self.b.close();self.b=Bridge(self.state)
        out=self.b.hook('codex','SessionStart',{'cwd':self.a,'session_id':'new'})
        self.assertIn('integration test pending',out['hookSpecificOutput']['additionalContext'])
        other=self.b.hook('codex','SessionStart',{'cwd':self.c,'session_id':'other'})
        self.assertNotIn('Apricot deployed',other['hookSpecificOutput']['additionalContext'])

    def test_concurrent_writers_no_loss(self):
        def save(i):
            b=Bridge(self.state)
            try:b.put(str(i),'claude',self.a,'note','parallel',f'fact {i}')
            finally:b.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(save,range(24)))
        self.assertEqual(self.b.status()['active_records'],24)
        self.assertEqual(self.b.status()['integrity'],'ok')

    def test_worktrees_share_project_identity(self):
        p=self.root/'repo';p.mkdir()
        subprocess.run(['git','init','-q',str(p)],check=True)
        subprocess.run(['git','-C',str(p),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','--allow-empty','-qm','init'],check=True)
        w=self.root/'worktree'
        subprocess.run(['git','-C',str(p),'worktree','add','-q','--detach',str(w)],check=True)
        self.assertEqual(canonical(str(p)),canonical(str(w)))

    def test_projectless_named_repo_handoff_and_ambiguous_names(self):
        repo=self.root/'orchard';repo.mkdir();subprocess.run(['git','init','-q',str(repo)],check=True)
        self.b.put('orchard','user',str(repo),'note','Setup','Use apricots')
        self.assertEqual(self.b.project_for_prompt(str(self.root),'Continue orchard'),canonical(str(repo)))
        self.b.hook('claude','UserPromptSubmit',{'cwd':str(self.root),'session_id':'loose','prompt':'Continue orchard'})
        self.b.hook('claude','Stop',{'cwd':str(self.root),'session_id':'loose','last_assistant_message':'Orchard progress'})
        self.assertIn('Orchard progress',' '.join(r['body'] for r in self.b.recall(str(repo))))
        other=self.root/'vineyard';other.mkdir();subprocess.run(['git','init','-q',str(other)],check=True)
        self.b.put('vineyard','user',str(other),'note','Setup','Use grapes')
        self.assertEqual(self.b.project_for_prompt(str(self.root),'Compare orchard and vineyard'),canonical(str(self.root)))
        self.assertEqual(self.b.project_for_prompt(str(repo),'Read vineyard'),canonical(str(repo)))

    def test_invalid_query_is_not_sql_or_fts_injection(self):
        self.b.put('a','user',self.a,'note','safe','Apricot test')
        self.b.recall(self.a,'" OR 1=1; DROP TABLE records; --')
        self.assertEqual(self.b.status()['active_records'],1)

    def test_installer_uninstall_preserves_new_user_changes(self):
        from manage import install,uninstall
        for rel in ['.codex','.claude','.agents/skills/example','.claude/skills/example']:
            (self.home/rel).mkdir(parents=True,exist_ok=True)
        (self.home/'.codex/AGENTS.md').write_text('Original instructions\n')
        (self.home/'.claude/CLAUDE.md').symlink_to(self.home/'.codex/AGENTS.md')
        (self.home/'.codex/config.toml').write_text('model = "unchanged"\n')
        (self.home/'.claude/settings.json').write_text(json.dumps({'theme':'dark','hooks':{'PreToolUse':[{'hooks':[{'type':'command','command':'original-hook'}]}]}}))
        install(self.state,self.home,launch=False)
        self.assertTrue((self.home/'.claude/skills').is_symlink())
        cfg=self.home/'.codex/config.toml'
        cfg.write_text(cfg.read_text()+'\n[hooks.state."'+str(self.home/'.codex/hooks.json')+':session_start:0:0"]\ntrusted_hash = "our-hook"\n\n[hooks.state."unrelated-hook"]\ntrusted_hash = "keep-me"\n')
        p=self.home/'.codex/AGENTS.md';p.write_text(p.read_text()+'\nNew user instruction\n')
        (self.home/'.claude/skills/example/new.txt').write_text('new knowledge')
        with self.assertRaises(RuntimeError):install(self.state,self.home,launch=False)
        uninstall(self.state)
        self.assertIn('New user instruction',p.read_text())
        self.assertNotIn('agent-bridge:start',p.read_text())
        self.assertFalse((self.home/'.claude/skills').is_symlink())
        self.assertEqual((self.home/'.claude/skills/example/new.txt').read_text(),'new knowledge')
        settings=json.loads((self.home/'.claude/settings.json').read_text())
        self.assertEqual(list(settings['hooks']),['PreToolUse'])
        self.assertEqual(settings['theme'],'dark')
        config=(self.home/'.codex/config.toml').read_text()
        self.assertIn('model = "unchanged"',config)
        self.assertNotIn('our-hook',config)
        self.assertNotIn('project_doc_fallback_filenames',config)
        self.assertIn('keep-me',config)

    def test_fallback_uninstall_keeps_user_added_filenames(self):
        from manage import fallback
        original='model = "keep"\n'
        added,changed=fallback(original,True);self.assertTrue(changed)
        self.assertEqual(fallback(added,False)[0],original)
        altered=added.replace('["CLAUDE.md"]','["CLAUDE.md", "TEAM.md"]')
        self.assertIn('["TEAM.md"]',fallback(altered,False)[0])

    def test_install_refuses_unreconciled_skills_without_mutation(self):
        from manage import install
        for prefix,value in [('.agents','left'),('.claude','right')]:
            p=self.home/prefix/'skills/example/SKILL.md';p.parent.mkdir(parents=True);p.write_text(value)
        with self.assertRaisesRegex(RuntimeError,'Unreconciled'):install(self.state,self.home,launch=False)
        self.assertFalse((self.home/'.local/bin/agent-bridge').exists())
        self.assertEqual((self.home/'.claude/skills/example/SKILL.md').read_text(),'right')




class PortableInstallTests(unittest.TestCase):
    def test_independent_global_instructions_are_preserved_on_both_agents(self):
        from manage import install, uninstall
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);home=base/'home';state=base/'state'
            (home/'.claude').mkdir(parents=True);(home/'.codex').mkdir()
            (home/'.claude/CLAUDE.md').write_text('Claude-specific original\n')
            (home/'.codex/AGENTS.md').write_text('Codex-specific original\n')
            install(state,home,launch=False)
            self.assertIn('agent-bridge:start',(home/'.claude/CLAUDE.md').read_text())
            self.assertIn('agent-bridge:start',(home/'.codex/AGENTS.md').read_text())
            config=json.loads((state/'config.json').read_text())
            self.assertFalse(config['sync_mcp']);self.assertEqual(config['shared_mcp_names'],[])
            uninstall(state)
            self.assertIn('Claude-specific original',(home/'.claude/CLAUDE.md').read_text())
            self.assertIn('Codex-specific original',(home/'.codex/AGENTS.md').read_text())
            self.assertNotIn('agent-bridge:start',(home/'.claude/CLAUDE.md').read_text())


if __name__=='__main__':unittest.main()
