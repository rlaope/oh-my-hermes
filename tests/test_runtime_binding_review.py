"""Finite PR review regressions at the runtime ownership boundary."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import runtime_paths as paths
from omh.plugin_bundle.omh.hooks import llm_hooks, tool_hooks, session_hooks


def native_modules(home, store, *, active=True, multiplex=False):
    def config(value):
        return {"plugins": {"entries": {"omh": {"settings": {"omh_home": str(value)}}}}}
    return {
        "hermes_constants": types.SimpleNamespace(get_hermes_home=lambda: home,
            get_hermes_home_override=lambda: str(home) if active else None),
        "agent.secret_scope": types.SimpleNamespace(is_multiplex_active=lambda: multiplex,
            current_secret_scope=lambda: None, get_secret=Mock(return_value=str(store)),
            build_profile_secret_scope=lambda home: {"OMH_HOME": str(store)}),
        "hermes_cli.config": types.SimpleNamespace(require_readable_config_before_write=Mock(return_value=config(store)),
            load_config_readonly=Mock(return_value=config(store))),
        "hermes_cli.managed_scope": types.SimpleNamespace(load_managed_config=lambda: {}),
        "agent.runtime_cwd": types.SimpleNamespace(resolve_context_cwd=lambda: None, resolve_agent_cwd=Path.cwd),
    }


class RuntimeBindingReviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home, self.store = self.root / 'profile', self.root / 'state'
        self.enterContext(patch.dict(os.environ, {"HOME": str(self.root), "USERPROFILE": str(self.root),
            "HERMES_HOME": str(self.home), "OMH_HOME": str(self.store)}))
        self.enterContext(patch.dict(sys.modules, {'hermes_constants': None}))

    def test_colocated_imports_do_not_select_native_config_or_secrets(self):
        modules = native_modules(self.home, self.root / 'native-state', active=False)
        with patch.dict(sys.modules, modules):
            self.assertEqual(paths.resolve_homes(), (self.store, self.home))
            self.assertEqual(paths.expand_path('$OMH_HOME'), self.store)
        modules['hermes_cli.config'].load_config_readonly.assert_not_called()
        modules['agent.secret_scope'].get_secret.assert_not_called()

    def test_active_host_missing_capabilities_is_bounded_before_config_io(self):
        required = {
            'hermes_constants': ['get_hermes_home', 'get_hermes_home_override'],
            'agent.secret_scope': ['is_multiplex_active', 'current_secret_scope', 'get_secret', 'build_profile_secret_scope'],
            'hermes_cli.config': ['require_readable_config_before_write', 'load_config_readonly'],
            'hermes_cli.managed_scope': ['load_managed_config'],
            'agent.runtime_cwd': ['resolve_context_cwd', 'resolve_agent_cwd'],
        }
        for module, names in required.items():
            for name in [None, *names]:
                with self.subTest(module=module, name=name):
                    modules = native_modules(self.home, self.store)
                    config = modules['hermes_cli.config']
                    if name is None:
                        modules[module] = None
                    else:
                        setattr(modules[module], name, None)
                    # A wholly absent Hermes is the supported standalone lane.
                    if module == 'hermes_constants' and name is None:
                        continue
                    with patch.dict(sys.modules, modules), self.assertRaises(paths.RuntimeBindingError) as caught:
                        paths.resolve_homes()
                    self.assertNotIn(str(self.root), str(caught.exception))
                    if callable(config.load_config_readonly):
                        config.load_config_readonly.assert_not_called()
                    if callable(config.require_readable_config_before_write):
                        config.require_readable_config_before_write.assert_not_called()

    def test_missing_constants_does_not_downgrade_an_active_native_scope(self):
        modules = native_modules(self.home, self.store, multiplex=True)
        modules['hermes_constants'] = None
        with patch.dict(sys.modules, modules), self.assertRaises(paths.RuntimeBindingError):
            paths.resolve_homes()
        with patch.object(paths, '_NATIVE_REGISTERED', True), self.assertRaises(paths.RuntimeBindingError):
            paths.resolve_homes()

    def test_unscoped_multiplexer_is_not_standalone(self):
        modules = native_modules(self.home, self.store, active=False, multiplex=True)
        with patch.dict(sys.modules, modules), self.assertRaises(paths.RuntimeBindingError):
            paths.resolve_homes()
        modules['hermes_cli.config'].load_config_readonly.assert_not_called()

    def test_literal_active_config_disagreement_is_rejected(self):
        modules = native_modules(self.home, self.store)
        modules['hermes_cli.config'].load_config_readonly.return_value = {
            'plugins': {'entries': {'omh': {'settings': {'omh_home': str(self.root / 'foreign')}}}}}
        with patch.dict(sys.modules, modules), self.assertRaises(paths.RuntimeBindingError):
            paths.resolve_homes()
        self.assertFalse(self.store.exists())
        self.assertFalse((self.root / 'foreign').exists())

    def test_missing_winning_leaf_cannot_select_an_effective_foreign_home(self):
        for missing in ('raw', 'effective'):
            with self.subTest(missing=missing):
                modules = native_modules(self.home, self.store)
                config = modules['hermes_cli.config']
                if missing == 'raw':
                    config.require_readable_config_before_write.return_value = {}
                else:
                    config.load_config_readonly.return_value = {}
                with patch.dict(sys.modules, modules), self.assertRaises(paths.RuntimeBindingError):
                    paths.resolve_homes()

    def test_filesystem_home_faults_are_typed_and_bounded(self):
        for exc in (OSError('PRIVATE_PATH'), RuntimeError('PRIVATE_PATH')):
            with self.subTest(error=type(exc).__name__), patch.object(Path, 'resolve', side_effect=exc):
                for call in (lambda: paths.expand_path(self.home), paths.default_hermes_home, paths.resolve_homes):
                    with self.assertRaises(paths.RuntimeBindingError) as caught:
                        call()
                    self.assertNotIn('PRIVATE_PATH', str(caught.exception))

    def test_cwd_resolution_fault_is_a_bounded_binding_error(self):
        modules = native_modules(self.home, self.store, multiplex=True)
        modules['agent.runtime_cwd'].resolve_context_cwd = Mock(side_effect=RuntimeError('PRIVATE_PATH'))
        for native in (False, True):
            with self.subTest(native=native), patch.dict(sys.modules, modules if native else {'hermes_constants': None}), \
                    patch.object(Path, 'cwd', side_effect=OSError('PRIVATE_PATH')):
                with self.assertRaises(paths.RuntimeBindingError) as caught:
                    paths.runtime_cwd()
                self.assertNotIn('PRIVATE_PATH', str(caught.exception))

    def test_binding_fault_precedes_hook_io_and_pre_tool_blocks(self):
        for module, name in ((llm_hooks, 'pre_llm_call'), (tool_hooks, 'pre_tool_call'),
                             (tool_hooks, 'post_tool_call'), (session_hooks, 'on_session_end')):
            for home_key in ('omh_home', 'hermes_home'):
                with self.subTest(hook=name, home=home_key):
                    def bind(value=None, *, hermes=False):
                        if hermes == (home_key == 'hermes_home'):
                            raise paths.RuntimeBindingError('PRIVATE_PATH')
                        return self.home if hermes else self.store
                    with patch.object(paths, 'plugin_home', side_effect=bind), \
                            patch.object(module, 'observe_plugin_hook_call') as observer:
                        result = getattr(module, name)(tool_name='read_file', host='host', session_id='s')
                    observer.assert_not_called()
                    self.assertTrue(result['omh_degradation']['degraded'])
                    self.assertNotIn('PRIVATE_PATH', json.dumps(result))
                    if name == 'pre_tool_call':
                        self.assertEqual(result['action'], 'block')

    def test_tool_rule_failure_is_not_swallowed_by_binding_guard(self):
        with patch.object(tool_hooks, 'toolcall_rule_directive', side_effect=RuntimeError('rule failure')):
            with self.assertRaisesRegex(RuntimeError, 'rule failure'):
                tool_hooks.pre_tool_call(tool_name='read_file')

    def test_user_name_expansion_is_rejected_without_os_lookup(self):
        for value in ('~root/file', '~some-user', '~another\\file'):
            with self.subTest(value=value), patch.object(Path, 'expanduser', side_effect=AssertionError('OS lookup')):
                with self.assertRaises(paths.RuntimeBindingError):
                    paths.expand_input_path(value)
        for value, expected in (('~/safe', self.root / 'safe'), (str(self.root / 'safe'), self.root / 'safe'),
                                ('safe', Path.cwd() / 'safe')):
            self.assertEqual(paths.expand_input_path(value), expected.resolve())

    def test_evidence_child_binding_failure_is_json_and_never_spawns(self):
        from omh.plugin_bundle.omh.tools import evidence_tool
        for root in ('default_omh_home', 'default_hermes_home'):
            with self.subTest(root=root), patch.object(paths, root, side_effect=paths.RuntimeBindingError('PRIVATE_PATH')), \
                    patch.object(evidence_tool.subprocess, 'run') as child:
                result = json.loads(evidence_tool.omh_evidence_handler({
                    'commands': ['git diff --check'], 'project_root': str(self.root)}))
            child.assert_not_called()
            self.assertIn('error', result)
            self.assertNotIn('PRIVATE_PATH', json.dumps(result))

    def test_native_model_home_overrides_are_rejected_before_observation(self):
        tools = {'delegate_route': ('omh_delegate_route', {'action': 'status'}),
                 'probe': ('omh_probe', {}), 'status': ('omh_status', {}), 'hud': ('omh_hud', {}),
                 'todo': ('omh_todo', {'action': 'show'}), 'chat': ('omh_interact', {'message': 'hello'}),
                 'run_summary': ('omh_run_summary', {})}
        with patch.dict(sys.modules, native_modules(self.home, self.store)):
            for file, (name, args) in tools.items():
                module = importlib.import_module('omh.plugin_bundle.omh.tools.' + file + '_tool')
                for field in ('omh_home', 'hermes_home'):
                    with self.subTest(tool=name, field=field), patch.object(module, 'observe_plugin_tool_call') as observer, \
                            patch.object(paths, 'plugin_home', side_effect=AssertionError('home lookup before rejection')) as resolver:
                        result = json.loads(getattr(module, name + '_handler')({**args, field: 'PRIVATE_PATH'}))
                    resolver.assert_not_called()
                    observer.assert_not_called()
                    self.assertIn('error', result)
                    self.assertNotIn('PRIVATE_PATH', json.dumps(result))
        self.assertFalse(self.store.exists())

    def test_project_artifact_routing_and_canonical_store_identity(self):
        from omh.paths import resolve_paths, project_artifact_dir
        project = self.root / 'project'
        (project / '.git').mkdir(parents=True)
        for native, routed in ((False, False), (True, False), (True, True)):
            with self.subTest(native=native, routed=routed):
                modules = native_modules(self.home, self.store, multiplex=routed) if native else {'hermes_constants': None}
                with patch.dict(sys.modules, modules):
                    selected = resolve_paths()
                    self.assertEqual(selected.omh_home_named, routed)
                    expected = self.store if routed else project / '.omh'
                    self.assertEqual(project_artifact_dir(selected, 'goals', cwd=project), expected / 'goals')
                    explicit = resolve_paths(self.store, self.home)
                    self.assertTrue(explicit.omh_home_named)
                    self.assertEqual(project_artifact_dir(explicit, 'goals', cwd=project), self.store / 'goals')
                    with patch.object(paths, 'runtime_cwd', return_value=None):
                        self.assertEqual(project_artifact_dir(selected, 'goals'), self.store / 'goals')
        try:
            (self.root / 'link').symlink_to(project, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'symlink unavailable: {type(exc).__name__}')
        link = self.root / 'link'
        with patch.object(paths, 'runtime_cwd', return_value=link):
            scoped = resolve_paths(scope='project')
            self.assertEqual(scoped.omh_home, project / '.omh')
            self.assertEqual(scoped.hermes_home, project / '.hermes')
            from omh.paths import find_project_root
            self.assertEqual(paths.runtime_cwd(), link)
            self.assertEqual(find_project_root(), project)
        self.assertEqual(paths.resolve_homes(link / '.omh', link / '.hermes'),
                         (scoped.omh_home, scoped.hermes_home))

    def test_explicit_blank_homes_fail_closed_in_both_scopes(self):
        from omh.paths import resolve_paths
        for scope in ('user', 'project'):
            for field in ('omh_home', 'hermes_home'):
                with self.subTest(scope=scope, field=field), self.assertRaises(paths.RuntimeBindingError):
                    resolve_paths(**{field: ''}, scope=scope)

    def test_standalone_observer_honors_explicit_homes_not_environment(self):
        from omh.plugin_bundle.omh.host_observation import observe_plugin_tool_call
        target = self.root / 'explicit'
        result = observe_plugin_tool_call('omh_status', {'omh_home': str(target),
            'hermes_home': str(self.home), 'observation': {'host': 'test-host', 'session_id': 's'}}, {})
        self.assertEqual(result['status'], 'observed')
        self.assertTrue(list((target / 'runtime').glob('*observations.jsonl')))
        self.assertFalse(self.store.exists())

    def test_native_observer_ignores_untrusted_home_metadata(self):
        from omh.plugin_bundle.omh.host_observation import observe_plugin_tool_call
        with patch.dict(sys.modules, native_modules(self.home, self.store)):
            result = observe_plugin_tool_call('omh_status', {'omh_home': str(self.root / 'foreign'),
                'observation': {'host': 'test-host', 'session_id': 's', 'omh_home': str(self.root / 'foreign')}}, {})
        self.assertEqual(result['status'], 'observed')
        self.assertTrue(self.store.exists())
        self.assertFalse((self.root / 'foreign').exists())

    def test_bundle_only_observer_honors_explicit_pair(self):
        import builtins
        from omh.plugin_bundle.omh.host_observation import observe_plugin_hook_call
        real_import = builtins.__import__
        def without_core(name, *args, **kwargs):
            if name == 'omh.paths':
                raise ModuleNotFoundError('core unavailable', name='omh.paths')
            return real_import(name, *args, **kwargs)
        target = self.root / 'bundle-explicit'
        with patch('builtins.__import__', side_effect=without_core):
            result = observe_plugin_hook_call('pre_llm_call', {'omh_home': str(target),
                'hermes_home': str(self.home), 'host': 'test-host', 'session_id': 's'})
        self.assertEqual(result['status'], 'observed')
        self.assertTrue((target / 'runtime/plugin_host_observations.jsonl').is_file())
        self.assertFalse(self.store.exists())

    def test_native_home_schema_descriptions_state_the_refusal(self):
        for name in ('chat', 'delegate_route', 'hud', 'probe', 'run_summary', 'status', 'todo'):
            module = importlib.import_module('omh.plugin_bundle.omh.tools.' + name + '_tool')
            for symbol, schema in vars(module).items():
                if not symbol.startswith('OMH_') or not symbol.endswith('_SCHEMA'):
                    continue
                for field, value in schema['parameters']['properties'].items():
                    if field in ('omh_home', 'hermes_home'):
                        self.assertIn('Native Hermes calls reject', value['description'])

    def test_memory_module_missing_symbols_is_optional_but_internal_faults_propagate(self):
        name = 'omh.plugin_bundle.omh._memory_import_review'
        original = importlib.import_module('omh.plugin_bundle.omh.memory_provider')
        def load():
            spec = importlib.util.spec_from_file_location(name, original.__file__)
            module = importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules, {name: module}):
                spec.loader.exec_module(module)
            return module
        for module in (None, types.ModuleType('agent.memory_provider')):
            with self.subTest(module=module), patch.dict(sys.modules, {'agent.memory_provider': module}):
                loaded = load()
                self.assertEqual(loaded.OmhMemoryProvider.__bases__, (object,))
                self.assertEqual(loaded.RecallStatus('OMH', 2).count, 2)
        class NativeBase:
            pass
        class NativeRecall:
            pass
        for base, recall in ((NativeBase, None), (None, NativeRecall), (NativeBase, NativeRecall)):
            module = types.ModuleType('agent.memory_provider')
            if base is not None:
                module.MemoryProvider = base
            if recall is not None:
                module.RecallStatus = recall
            with patch.dict(sys.modules, {'agent.memory_provider': module}):
                loaded = load()
                self.assertEqual(loaded.OmhMemoryProvider.__bases__, (base or object,))
                if recall is not None:
                    self.assertIs(loaded.RecallStatus, recall)
        for failure in (ImportError('internal failure'), ModuleNotFoundError('internal failure', name='host_dependency')):
            with patch.object(paths, 'import_module', side_effect=failure), self.assertRaises(type(failure)) as caught:
                load()
            self.assertIs(caught.exception, failure)
        # The ordinary module and its class identities were never replaced.


if __name__ == '__main__':
    unittest.main()
