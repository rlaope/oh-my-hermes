"""Shipped search guidance contracts; fixtures are synthetic, not retrieval."""
from __future__ import annotations

import unittest

from _local_package import load_local_package
from _module_patch import patch_modules

load_local_package()


class SearchGuidanceTests(unittest.TestCase):
    def test_native_constraints_and_noncontent_transaction_metadata_are_documented(self):
        from pathlib import Path
        from omh.skills.search_guidance import METHOD
        from omh.skills.search_payloads import fields_markdown

        doc = (Path(__file__).resolve().parents[1] / 'docs/SEARCH-AMPLIFICATION.md').read_text(encoding='utf-8')
        for text in (METHOD, doc):
            compact = ' '.join(text.split())
            for claim in ('operation flags', 'numeric UTC clock floor', 'last delivered state',
                          'serialization', 'planned/current operations'):
                self.assertIn(claim, compact)
            self.assertNotIn('hash-only', text.lower())
        fields = ' '.join(fields_markdown().split())
        self.assertIn('complete response', fields)
        self.assertIn('no state or retry reservation', fields)

    def test_existing_research_skills_ship_progressive_search_method(self):
        from omh.skills.skill_record import project, skill_record
        from omh.skills.catalog import omh_skill_display_name

        for name in ('web-research', 'source-finder', 'research'):
            for target in ('hermes', 'agent-skills'):
                with self.subTest(name=name, target=target):
                    files = project(skill_record(name), target)
                    prefix = omh_skill_display_name(name) + '/'
                    body = files[prefix + 'SKILL.md']
                    self.assertIn('references/search-method.md', body)
                    method = files[prefix + 'references/search-method.md']
                    steps = ['Discover capabilities', 'Plan', 'Search and read', 'Merge', 'Assess', 'Bounded retry']
                    positions = [method.index('## ' + step) for step in steps]
                    self.assertEqual(positions, sorted(positions))
                    self.assertIn('skill-only fallback', method)
                    self.assertIn('references/search-fields.md', method)
                    self.assertIn('references/search-examples.md', method)
                    self.assertNotIn('/Users/', method)
                    self.assertNotIn('search_spec/v1', body)

    def test_shipped_examples_execute_real_registered_handler_and_native_producers(self):
        import json
        import re
        from omh.plugin_bundle.omh import register
        from omh.skills.skill_record import project, skill_record
        from omh.workflows.search_amplification import build_search_plan, assess_search_coverage
        from omh.workflows.search_evidence import merge_search_candidates

        class Host:
            def __init__(self):
                self.tools = {}

            def register_tool(self, name, toolset, schema, handler, **kwargs):
                self.tools[name] = handler

            def register_hook(self, *args, **kwargs):
                pass

        host = Host()
        register(host)
        for target in ('hermes', 'agent-skills'):
            files = project(skill_record('web-research'), target)
            self.assertIn('omh-web-research/references/search-fields.md', files, 'nested payload definitions must ship')
            fields = files['omh-web-research/references/search-fields.md']
            schema = json.loads(re.findall(r'```json\n(.*?)\n```', fields, re.S)[0])
            self.assertIn('spec', schema['$defs'])
            self.assertIn('merge_context', schema['$defs'])
            self.assertIn('assessment_input', schema['$defs'])
            self.assertIn('read', schema['$defs'])
            self.assertIn('previous_state', schema['$defs']['assessment_input']['properties'])
            text = files['omh-web-research/references/search-examples.md']
            scenarios = json.loads(re.findall(r'```json\n(.*?)\n```', text, re.S)[0])
            self.assertTrue(scenarios['synthetic_only'])
            for scenario in scenarios['scenarios']:
                context = {'session_id': self.id() + target + scenario['name'], 'user_task': scenario['host_request']}
                for args in scenario['calls']:
                    payload = args['payload']
                    if args['action'] == 'plan':
                        expected = build_search_plan(**payload)
                    elif args['action'] == 'merge':
                        expected = merge_search_candidates(**payload)
                    else:
                        expected = assess_search_coverage(**payload)
                    actual = json.loads(host.tools['omh_search'](args, **context))
                    self.assertFalse(actual['degraded'], actual)
                    self.assertEqual(actual['result'], expected)
                    if args['action'] == 'assess' and scenario['name'] == 'bounded_retry':
                        first = payload['observations']['previous_state'] is None
                        self.assertEqual(actual['result']['follow_up'], 'search_once' if first else 'partial_answer')
                        self.assertEqual(actual['result']['follow_up_query_ids'], ['q1'] if first else [])
                self.assertEqual(actual['result']['follow_up'], scenario['expected_follow_up'])
            self.assertIn('search_once', text)
            self.assertIn('full_text', text)
            self.assertNotIn('/Users/', fields + text)

    def test_user_document_states_support_privacy_and_unmeasured_targets(self):
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / 'docs/SEARCH-AMPLIFICATION.md'
        self.assertTrue(path.is_file(), 'English user guide is missing')
        doc = path.read_text(encoding='utf-8')
        for text in ('Find datasets for browser agent benchmarks', 'Native Hermes', 'Portable',
                     'Unsupported', 'AutoRAG MCP', 'process-local', 'session_id', 'user_task',
                     '256 sessions', '32 requests', 'unmeasured', '10 percentage points',
                     '1.2', '1.5', 'No mandatory', 'permission', 'retention'):
            self.assertIn(text, doc)
        self.assertNotIn('/Users/', doc)

    def test_reference_closure_remains_usable_outside_source_tree(self):
        import json
        from pathlib import Path
        import re
        import tempfile
        from omh.skills.skill_record import project, skill_record
        from omh.skills.catalog import omh_skill_display_name

        for target in ('hermes', 'agent-skills'):
            for name in ('web-research', 'source-finder', 'research'):
                with self.subTest(target=target, name=name), tempfile.TemporaryDirectory() as tmp:
                    files = project(skill_record(name), target)
                    for relative, content in files.items():
                        path = Path(tmp) / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(content, encoding='utf-8')
                    base = Path(tmp) / omh_skill_display_name(name)
                    for path in base.rglob('*.md'):
                        content = path.read_text(encoding='utf-8')
                        if 'search-' not in path.name and path.name != 'SKILL.md':
                            continue
                        for ref in re.findall(r'`(references/search-[a-z]+\.md)`', content):
                            self.assertTrue((base / ref).is_file(), (path, ref))
                    schema = json.loads(re.findall(r'```json\n(.*?)\n```', (base / 'references/search-fields.md').read_text(encoding='utf-8'), re.S)[0])
                    refs = re.findall(r'"\$ref":\s*"([^"]+)"', json.dumps(schema))
                    self.assertTrue(refs)
                    for ref in refs:
                        self.assertTrue(ref.startswith('#/$defs/'), ref)
                        self.assertIn(ref.removeprefix('#/$defs/'), schema['$defs'])
                    examples = (base / 'references/search-examples.md').read_text(encoding='utf-8')
                    self.assertTrue(json.loads(re.findall(r'```json\n(.*?)\n```', examples, re.S)[0])['synthetic_only'])

    def test_helper_failures_match_the_documented_fallback(self):
        import json
        from omh.plugin_bundle.omh.tools.search_tool import omh_search_handler
        from omh.skills.search_payloads import example_scenarios
        from omh.skills.search_guidance import METHOD

        args = example_scenarios()['scenarios'][0]['calls'][0]
        unavailable = json.loads(omh_search_handler(args))
        self.assertEqual(unavailable['error'], 'host_context_unavailable')
        with patch_modules({'omh.workflows.search_amplification': None}):
            unavailable = json.loads(omh_search_handler(args, session_id=self.id(), user_task='Synthetic backend unavailable'))
        self.assertEqual(unavailable['error'], 'backend_unavailable')
        self.assertNotIn('result', unavailable)
        for reason in ('plugin is disabled', 'tool is absent/disabled', 'backend is unavailable',
                       'host context is unavailable', 'capacity is exhausted'):
            self.assertIn(reason, ' '.join(METHOD.split()))

    def test_specialist_procedure_generated_parity(self):
        from pathlib import Path
        from omh.skills.catalog import builtin_definitions
        from omh.skills.procedure_rendering import specialist_procedure_reference_markdown
        from omh.skills.render import translate_sibling_mentions
        from omh.skills.skill_record import project, skill_record

        root = Path(__file__).resolve().parents[1]
        for name in ('web-research', 'source-finder', 'research'):
            for target, directory in (('hermes', 'skills'), ('agent-skills', 'agent-skills')):
                files = project(skill_record(name), target)
                for relative, content in files.items():
                    if '/references/search-' in relative:
                        path = root / directory / relative
                        self.assertTrue(path.is_file(), relative)
                        self.assertEqual(path.read_text(encoding='utf-8'), content, relative)
        for definition in builtin_definitions():
            if definition.procedure_steps:
                refs = {template.relative_path: template.content for template in skill_record(definition.name).references()}
                # The shipped reference names siblings by their loadable label; the generator writes catalog names.
                self.assertEqual(
                    refs['references/procedure.md'],
                    translate_sibling_mentions(specialist_procedure_reference_markdown(definition), owner=definition.name),
                )


if __name__ == '__main__':
    unittest.main()
