"""Synthetic-only current OMH source probes; assertions express desired isolation."""
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
# Run with the native scripts/run_tests.sh; no native dependency in OMH CI.
BUNDLE = REPO / 'src/plugin_bundle/omh'
MARKER = 'SYNTHETIC_PRIVATE_CONSOLIDATION_ONLY'


def record(row):
    print('OBSERVED=' + json.dumps(row, sort_keys=True))


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    tmp_path = tmp_path.resolve()
    root = tmp_path / '.hermes'
    public = root / 'profiles' / 'public'
    private_store, public_store = tmp_path / 'private-store', tmp_path / 'public-store'
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('HERMES_HOME', str(root))
    monkeypatch.setenv('OMH_HOME', str(private_store))
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('PYTHONDONTWRITEBYTECODE', '1')
    for home, store in ((root, private_store), (public, public_store)):
        home.mkdir(parents=True, exist_ok=True)
        (home / 'config.yaml').write_text(
            'memory:\n  provider: omh\nplugins:\n  enabled: [omh]\n'
            '  entries:\n    omh:\n      settings:\n        omh_home: ' + str(store) + '\n'
            'terminal:\n  backend: local\n')
        (home / '.env').write_text(f'OMH_HOME={store}\n')
        shutil.copytree(BUNDLE, home / 'plugins/omh', ignore=shutil.ignore_patterns('__pycache__'))
        # Preserve bundled config bytes: no integrity bypass or implementation edit.
        (store / 'memory').mkdir(parents=True)
        (store / 'runtime').mkdir()
        (store / 'runtime/state.json').write_text(json.dumps({'last_run_id': 'synthetic-' + store.name}))
    from agent.secret_scope import set_multiplex_active
    from hermes_cli.plugins import _reset_plugin_managers_for_tests, PluginManager
    import hermes_cli.plugins as hp
    # Only discover the two synthetic OMH copies, never other installed plugin code.
    monkeypatch.setattr(hp, 'get_bundled_plugins_dir', lambda: tmp_path / 'no-bundled')
    monkeypatch.setattr(PluginManager, '_scan_entry_points', lambda self: [])
    _reset_plugin_managers_for_tests()
    set_multiplex_active(True)
    yield root, public, private_store, public_store
    set_multiplex_active(False)
    _reset_plugin_managers_for_tests()


def load(home, order):
    from gateway.run import _profile_runtime_scope
    from plugins.memory import load_memory_provider
    from hermes_cli.plugins import get_plugin_manager
    with _profile_runtime_scope(home):
        manager = get_plugin_manager()
        if order == 'general-first':
            manager.discover_and_load()
        provider = load_memory_provider('omh', register_skills=False)
        assert provider is not None
        if order == 'memory-first':
            manager.discover_and_load()
        return provider, manager


def snapshot(store):
    return {str(path.relative_to(store)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in store.rglob("*") if path.is_file()}


def seed(store, provider):
    mod = importlib.import_module(type(provider).__module__.rsplit('.', 1)[0] + '.memory_dreaming')
    (store / 'memory/consolidation.json').write_text(json.dumps({
        'schema_version': mod.DREAMING_HANDOFF_SCHEMA_VERSION, 'due': True,
        'trigger': 'synthetic-session', 'reasons': [MARKER], 'session_id': 'synthetic-private',
        'requested_of_executor': []}))


def exercise(home, provider, manager):
    from gateway.run import _profile_runtime_scope
    from hermes_constants import get_hermes_home
    from agent.secret_scope import get_secret
    from tools.registry import registry
    with _profile_runtime_scope(home):
        provider.initialize('synthetic-public', hermes_home=str(home), platform='discord',
                            active_profile='public', shared_surface=True, cwd=str(home))
        pack = provider.prefetch(session_id='synthetic-public')
        provider.on_turn_start(1, 'synthetic question')
        memory_result = registry.get_entry('omh_memory').handler({'action': 'consolidation'}, session_id='synthetic-public')
        todo_result = json.loads(registry.get_entry('omh_todo').handler(
            {'action': 'set', 'title': 'synthetic public plan', 'items': [{'text': 'synthetic task', 'state': 'pending'}]},
            session_id='synthetic-public'))
        hook = manager._hooks['on_session_end'][0]
        hook_result = hook(session_id='synthetic-public')
        module = importlib.import_module(type(provider).__module__)
        digest = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        return {'native_home': str(get_hermes_home()), 'scoped_omh_env': get_secret('OMH_HOME'),
                'provider_home': str(provider._omh_home), 'provider_source': module.__file__,
                'current_source_digest_matches': digest == hashlib.sha256((BUNDLE / 'memory_provider.py').read_bytes()).hexdigest(),
                'provider_marker': MARKER in pack, 'tool_marker': MARKER in memory_result,
                'todo_status': todo_result.get('status'), 'session_hook': hook_result,
                'on_session_end_hook_count': len(manager._hooks['on_session_end'])}


@pytest.mark.parametrize('order', ['general-first', 'memory-first'])
@pytest.mark.parametrize('mode', ['standalone', 'multiplex'])
def test_public_provider_tools_and_hooks(fixture, monkeypatch, order, mode):
    root, public, private_store, public_store = fixture
    if mode == 'standalone':
        from agent.secret_scope import set_multiplex_active
        set_multiplex_active(False)
        monkeypatch.setenv('HERMES_HOME', str(public))
        monkeypatch.setenv('OMH_HOME', str(public_store))
    provider, manager = load(public, order)
    seed(private_store, provider)
    before = snapshot(private_store)
    observed = exercise(public, provider, manager)
    assert snapshot(private_store) == before
    observed.update({'case': mode, 'order': order,
        'private_dreaming_written': (private_store / 'memory/dreaming.json').exists(),
        'public_dreaming_written': (public_store / 'memory/dreaming.json').exists(),
        'private_files': sorted(str(p.relative_to(private_store)) for p in private_store.rglob('*') if p.is_file()),
        'public_files': sorted(str(p.relative_to(public_store)) for p in public_store.rglob('*') if p.is_file())})
    record(observed)
    assert observed['current_source_digest_matches']
    assert not observed['provider_marker'] and not observed['tool_marker']
    assert observed['provider_home'] == str(public_store)
    assert observed['public_dreaming_written'] and not observed['private_dreaming_written']
    assert observed['on_session_end_hook_count'] == 1
    assert observed['todo_status'] == 'written'
    assert observed['session_hook']['path'].startswith(str(public_store))


@pytest.mark.parametrize('profile_order', ['private-first', 'public-first'])
def test_interleaved_tasks(fixture, profile_order):
    root, public, private_store, public_store = fixture
    order = (root, public) if profile_order == 'private-first' else (public, root)
    loaded = {home: load(home, 'memory-first') for home in order}
    seed(private_store, loaded[public][0])
    from gateway.run import _profile_runtime_scope
    from hermes_constants import get_hermes_home
    from agent.secret_scope import get_secret
    async def run(home):
        with _profile_runtime_scope(home):
            await asyncio.sleep(0)
            provider, manager = loaded[home]
            module = importlib.import_module(type(provider).__module__.rsplit('.', 1)[0] + '.runtime_reader')
            return {'hermes_home': str(get_hermes_home()), 'scoped_env': get_secret('OMH_HOME'),
                    'provider_home': str(provider._omh_home),
                    'reader_home': str(module._default_omh_home()),
                    'reader_hermes_home': str(module._default_hermes_home()),
                    'module': type(provider).__module__, 'manager_scope': manager.scope_key}
    async def tasks():
        return await asyncio.gather(run(root), run(public))
    rows = asyncio.run(tasks())
    record({'case': 'interleaved', 'profile_order': profile_order, 'rows': rows,
            'process_omh_home_unchanged': os.environ['OMH_HOME'] == str(private_store)})
    assert rows[0]['module'] != rows[1]['module']
    assert rows[0]['manager_scope'] != rows[1]['manager_scope']
    assert rows[1]['scoped_env'] == str(public_store)
    assert rows[1]['provider_home'] == rows[1]['reader_home'] == str(public_store)
    assert rows[1]['reader_hermes_home'] == str(public)


@pytest.mark.parametrize('core_available', [False, True], ids=['bundle-fallback', 'current-core'])
def test_remaining_binding_seams(fixture, core_available, monkeypatch):
    root, public, private_store, public_store = fixture
    if core_available:
        sys.path.insert(0, str(REPO / 'src'))
        import omh
        assert Path(omh.__file__).resolve().is_relative_to(REPO)
    else:
        # Pytest may add the checkout shim to sys.path. Force the genuinely
        # package-absent copied-bundle path, independent of collection order.
        class WithoutCore:
            def find_spec(self, fullname, path=None, target=None):
                if fullname == 'omh' or fullname.startswith('omh.'):
                    raise ModuleNotFoundError('OMH core intentionally absent', name='omh')
                return None
        for name in list(sys.modules):
            if name == 'omh' or name.startswith('omh.'):
                monkeypatch.delitem(sys.modules, name)
        monkeypatch.setattr(sys, 'meta_path', [WithoutCore(), *sys.meta_path])
    provider, manager = load(public, 'memory-first')
    from gateway.run import _profile_runtime_scope
    from hermes_cli.plugins import PluginContext, PluginManifest
    from plugins.memory import _ProviderCollector
    with _profile_runtime_scope(public):
        context = PluginContext(PluginManifest(name='omh', key='omh'), manager)
        base = type(provider).__module__.rsplit('.', 1)[0]
        observer = importlib.import_module(base + '.host_observation')
        journal = observer.observe_plugin_hook_call('pre_llm_call',
                    {'session_id': 'synthetic-public', 'host': 'synthetic-host'})
        evidence = importlib.import_module(base + '.tools.evidence_tool')
        env = evidence._minimal_child_environment(str(public / 'pycache'))
        import subprocess
        code = ('import sys,json; sys.path.insert(0,' + repr(str(REPO / 'src')) + '); '
                'from omh.paths import default_omh_home, default_hermes_home; '
                'print(json.dumps([str(default_omh_home()),str(default_hermes_home())]))')
        child = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, check=True)
        row = {'case': 'remaining-seams', 'core_available': core_available,
               'host_get_config_correct': context.get_config('omh_home') == str(public_store),
               'collector_has_get_config': hasattr(_ProviderCollector('omh'), 'get_config'),
               'provider_home_correct': provider._omh_home == public_store,
               'journal_result': journal,
               'private_journal_files': sorted(str(p.relative_to(private_store)) for p in private_store.rglob('*') if p.is_file()),
               'public_journal_files': sorted(str(p.relative_to(public_store)) for p in public_store.rglob('*') if p.is_file()),
               'child_resolved_homes': json.loads(child.stdout),
               'child_has_home_overrides': 'HERMES_HOME' in env or 'OMH_HOME' in env}
        if core_available:
            from omh.paths import resolve_paths
            row['core_default_homes'] = [str(resolve_paths().omh_home), str(resolve_paths().hermes_home)]
            row['core_explicit_homes'] = [str(resolve_paths(public_store, public).omh_home), str(resolve_paths(public_store, public).hermes_home)]
        record(row)
        assert row['host_get_config_correct']
        assert row['provider_home_correct']
        assert not (private_store / 'runtime/plugin-host-observations.jsonl').exists()
        assert row['child_resolved_homes'] == [str(public_store), str(public)]
        assert row['child_has_home_overrides']


def test_tool_hook_third_home(fixture):
    root, public, private_store, public_store = fixture
    provider, manager = load(public, 'general-first')
    from gateway.run import _profile_runtime_scope
    with _profile_runtime_scope(public):
        manager._hooks['pre_tool_call'][0](tool_name='read_file', args={'path': 'synthetic.txt'},
            session_id='synthetic-public', tool_call_id='synthetic-call', turn_id='synthetic-turn')
        manager._hooks['post_tool_call'][0](tool_name='read_file', session_id='synthetic-public',
            tool_call_id='synthetic-call')
    third_home = root.parent / '.omh'
    row = {'case': 'tool-hook-third-home',
           'public_burst_written': (public_store / 'runtime/tool-bursts.json').exists(),
           'third_home_files': sorted(str(p.relative_to(third_home)) for p in third_home.rglob('*') if p.is_file())}
    record(row)
    assert row['public_burst_written']
    assert not row['third_home_files']


def test_real_host_turn_order(fixture, monkeypatch):
    root, public, private_store, public_store = fixture
    provider, manager = load(public, 'memory-first')
    seed(private_store, provider)
    monkeypatch.chdir(public)
    from gateway.run import _profile_runtime_scope
    from agent.memory_manager import MemoryManager
    from agent.turn_context import _memory_turn_start_and_prefetch
    from types import SimpleNamespace
    with _profile_runtime_scope(public):
        memory = MemoryManager()
        memory.add_provider(provider)
        memory.initialize_all('synthetic-public', platform='discord', agent_context='primary')
        initialized_pack = provider.prefetch(session_id='synthetic-public')
        agent = SimpleNamespace(_memory_manager=memory, _user_turn_count=1,
                                session_id='synthetic-public', _emit_status=lambda message: None)
        actual_pack = _memory_turn_start_and_prefetch(agent, 'Explain this synthetic project isolation question')
        row = {'case': 'real-host-turn-order', 'initialized_pack_marker': MARKER in initialized_pack,
               'native_turn_pack_marker': MARKER in actual_pack, 'native_turn_pack_empty': not actual_pack,
               'private_dreaming_written': (private_store / 'memory/dreaming.json').exists(),
               'public_dreaming_written': (public_store / 'memory/dreaming.json').exists()}
        record(row)
        assert not row['native_turn_pack_marker']
        assert not row['private_dreaming_written'] and row['public_dreaming_written']




@pytest.mark.parametrize('binding', ['settings', 'legacy', 'scoped-env', 'shared', 'missing', 'blank', 'invalid', 'malformed', 'scoped-variable', 'ambiguous-variable', 'relative'])
def test_native_binding_precedence_and_fail_closed(fixture, binding):
    root, public, private_store, public_store = fixture
    from gateway.run import _profile_runtime_scope
    from hermes_constants import get_hermes_home
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    sys.path.insert(0, str(REPO / 'src'))
    from omh.plugin_bundle.omh.runtime_paths import RuntimeBindingError, resolve_homes
    expected = public_store
    entry = {'settings': {'omh_home': str(public_store)}}
    env = {'OMH_HOME': str(private_store)}
    if binding == 'legacy':
        entry = {'config': {'omh_home': str(public_store)}}
    elif binding == 'scoped-env':
        entry, env = {}, {'OMH_HOME': str(public_store)}
    elif binding == 'shared':
        entry = {'settings': {'omh_home': str(private_store)}}
        expected = private_store
    elif binding == 'missing':
        entry, env = {}, {}
    elif binding == 'blank':
        entry = {'settings': {'omh_home': '   '}}
    elif binding == 'invalid':
        entry = {'settings': {'omh_home': []}}
    elif binding == 'scoped-variable':
        entry = {'settings': {'omh_home': '$HERMES_HOME/state'}}
        expected = public / 'state'
    elif binding == 'relative':
        entry = {'settings': {'omh_home': 'state'}}
        expected = public / 'state'
    elif binding == 'ambiguous-variable':
        entry = {'settings': {'omh_home': '${HERMES_HOME}/state'}}
    config = {'plugins': {'entries': {'omh': entry}}}
    (public / 'config.yaml').write_text('invalid: [' if binding == 'malformed' else json.dumps(config))
    with _profile_runtime_scope(public):
        token = set_secret_scope(env)
        try:
            assert get_hermes_home() == public
            if binding in {'missing', 'blank', 'invalid', 'malformed', 'ambiguous-variable'}:
                with pytest.raises(RuntimeBindingError):
                    resolve_homes()
            else:
                assert resolve_homes() == (expected, public)
            # Complete operator pairs stay usable, even for offline/shared stores.
            assert resolve_homes(private_store, root) == (private_store, root)
            with pytest.raises(RuntimeBindingError):
                resolve_homes(hermes_home=root)
        finally:
            reset_secret_scope(token)


def test_unscoped_multiplexer_and_explicit_offline_pair(fixture):
    root, public, private_store, public_store = fixture
    sys.path.insert(0, str(REPO / 'src'))
    from omh.plugin_bundle.omh.runtime_paths import RuntimeBindingError, resolve_homes, default_hermes_home
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    home_token, secret_token = set_hermes_home_override(None), set_secret_scope(None)
    try:
        with pytest.raises(RuntimeBindingError):
            resolve_homes()
        with pytest.raises(RuntimeBindingError):
            default_hermes_home()
        assert resolve_homes(public_store, public) == (public_store, public)
    finally:
        reset_hermes_home_override(home_token)
        reset_secret_scope(secret_token)


def test_model_home_injection_and_bound_background_provider(fixture, monkeypatch):
    root, public, private_store, public_store = fixture
    provider, manager = load(public, 'general-first')
    from gateway.run import _profile_runtime_scope
    from tools.registry import registry
    base = type(provider).__module__.rsplit('.', 1)[0]
    observer = importlib.import_module(base + '.host_observation')
    evidence = importlib.import_module(base + '.tools.evidence_tool')
    monkeypatch.setenv('SYNTHETIC_ACCESS_TOKEN', 'never-pass-to-child')
    with _profile_runtime_scope(public):
        provider.initialize('same-session', hermes_home=public, cwd=public, platform='cli')
        # The home-looking fields are observations/model text, not authority.
        injection = {'host': 'synthetic-host', 'session_id': 'same-session',
                     'omh_home': str(private_store), 'hermes_home': str(root)}
        record = observer.observe_plugin_tool_call('omh_memory', {'observation': injection}, injection)
        assert record and record['status'] == 'observed'
        manager._hooks['pre_tool_call'][0](tool_name='read_file', args={'path': 'nothing'}, **injection)
        registry.get_entry('omh_todo').handler({'action': 'show', 'omh_home': str(private_store)})
        env = evidence._minimal_child_environment(str(public / 'cache'))
        assert env['OMH_HOME'] == str(public_store) and env['HERMES_HOME'] == str(public)
        assert 'SYNTHETIC_ACCESS_TOKEN' not in env
        from contextvars import copy_context
        work = copy_context()
    with _profile_runtime_scope(root):
        # Provider work remains attached to its instance even after scope exit.
        work.run(provider.on_turn_start, 1, 'A synthetic queued turn')
        with pytest.raises(ValueError, match='another profile'):
            provider.initialize('different-session', hermes_home=root)
    assert not (private_store / 'memory/dreaming.json').exists()
    assert not (private_store / 'runtime/tool-bursts.json').exists()
    assert (public_store / 'memory/dreaming.json').exists()
    assert (public_store / 'runtime/tool-bursts.json').exists()


def test_positive_recall_after_real_turn_and_native_queue(fixture):
    root, public, private_store, public_store = fixture
    provider, _ = load(public, 'memory-first')
    from gateway.run import _profile_runtime_scope
    from agent.memory_manager import MemoryManager
    from agent.turn_context import _memory_turn_start_and_prefetch
    from types import SimpleNamespace
    blocks = importlib.import_module(type(provider).__module__.rsplit('.', 1)[0] + '.memory_blocks')
    block = blocks.build_memory_block(label='profile-preference', value='SYNTHETIC_PUBLIC_RECALL',
                                      description='Synthetic profile preference', tier='system')
    blocks.write_memory_block(public_store, blocks.approve_memory_block(block, reviewer_claim='user'))
    with _profile_runtime_scope(public):
        memory = MemoryManager()
        memory.add_provider(provider)
        memory.initialize_all('synthetic-public', hermes_home=public, platform='cli', agent_context='primary')
        agent = SimpleNamespace(_memory_manager=memory, _user_turn_count=1,
                                session_id='synthetic-public', _emit_status=lambda message: None)
        actual_pack = _memory_turn_start_and_prefetch(agent, 'Explain the synthetic profile preference')
        # Existing upstream on_turn_start invalidates the pack. Do not repair or
        # conceal that separate lifecycle behavior in a root-binding change.
        assert MARKER not in actual_pack
        memory.queue_prefetch_all('synthetic preference', session_id='synthetic-public')
        assert memory.flush_pending(timeout=10)
        positive = memory.prefetch_all('synthetic preference', session_id='synthetic-public')
        assert 'SYNTHETIC_PUBLIC_RECALL' in positive
        assert MARKER not in positive
        assert memory.describe_recall()
        memory.shutdown_all()
    assert not (private_store / 'memory/dreaming.json').exists()
    assert (public_store / 'memory/dreaming.json').exists()


@pytest.mark.parametrize('identity_source', ['explicit', 'remote', 'missing', 'absent-cwd'])
def test_project_identity_stays_bound_across_profile_scopes(fixture, monkeypatch, identity_source):
    root, public, private_store, public_store = fixture
    private_project = root.parent / 'private' / 'same-name'
    public_project = root.parent / 'public' / 'same-name'
    private_identity = 'prj:' + 'b' * 64
    public_identity = 'prj:' + 'a' * 64
    for project, identity in ((private_project, private_identity), (public_project, public_identity)):
        (project / '.omh').mkdir(parents=True)
        (project / '.omh/project-identity.json').write_text(json.dumps({
            'schema_version': 'project_identity_file/v1', 'identity': identity,
            'created_at': '2026-01-01T00:00:00Z', 'resolver_version': 'project_identity/v2'}))
    if identity_source in {'remote', 'missing'}:
        (public_project / '.omh/project-identity.json').unlink()
        (public_project / '.git').mkdir()
        (public_project / '.git/config').write_text(
            '[remote "origin"]\n url = git@EXAMPLE.test:team/public.git\n'
            if identity_source == 'remote' else '[core]\n bare = false\n')
        public_identity = ('repo:' + hashlib.sha256(b'example.test/team/public').hexdigest()[:32]
                           if identity_source == 'remote' else '')
    if identity_source == 'absent-cwd':
        public_identity = ''
    monkeypatch.chdir(private_project)
    provider, _ = load(public, 'memory-first')
    from gateway.run import _profile_runtime_scope
    from agent.runtime_cwd import set_session_cwd, _SESSION_CWD, resolve_context_cwd
    from agent.memory_manager import MemoryManager
    sys.path.insert(0, str(REPO / 'src'))
    from omh.paths import resolve_paths
    from omh.workflows import memory as memory_api
    with _profile_runtime_scope(public):
        paths = resolve_paths(public_store, public)
        records = {}
        for label, identity in (('public', public_identity or 'prj:' + 'a' * 64), ('private', private_identity)):
            candidate = memory_api.capture_project_memory_candidate(paths,
                'Synthetic ' + label + ' project sentinel', scope_ref=identity, retention_class='durable')['candidate']
            records[label] = memory_api.approve_project_memory_candidate(paths, candidate['candidate_id'])['record']['record_id']
        from tools.terminal_scope import set_terminal_scope, reset_terminal_scope
        terminal_token = set_terminal_scope({})
        token = set_session_cwd(None if identity_source == 'absent-cwd' else str(public_project))
        try:
            assert resolve_context_cwd() == (None if identity_source == 'absent-cwd' else public_project)
            before = snapshot(private_store), snapshot(private_project)
            memory = MemoryManager()
            memory.add_provider(provider)
            memory.initialize_all('synthetic-identity', platform='cli', agent_context='primary')
        finally:
            _SESSION_CWD.reset(token)
            reset_terminal_scope(terminal_token)
    with _profile_runtime_scope(root):
        token = set_session_cwd(str(private_project))
        try:
            # Both direct re-render and queued work must keep the initialized cwd;
            # a genuinely absent public cwd must not re-resolve this foreign one.
            pack = provider.render_pack()
            provider.queue_prefetch()
            pack += provider.prefetch()
            receipt = provider.latest_prefetch_receipt()
            assert receipt is not None
            assert receipt['schema_version'] == 'omh_memory_prefetch_receipt/v3'
            assert receipt['resolver_version'] == 'project_identity/v2'
            assert receipt['project_identity'] == public_identity
            assert records['private'] not in pack
            if public_identity:
                assert records['public'] in pack
            else:
                assert records['public'] not in pack
                assert receipt['lens']['scope_allowlist'] == []
            assert provider._project_home == (None if identity_source == 'absent-cwd' else public_project / '.omh')
            assert provider._omh_home == public_store
            assert (snapshot(private_store), snapshot(private_project)) == before
        finally:
            _SESSION_CWD.reset(token)
            memory.shutdown_all()


def test_project_home_uses_host_logical_cwd(fixture, monkeypatch):
    root, public, private_store, public_store = fixture
    private_project, public_project = root.parent / 'private-project', root.parent / 'public-project'
    for project in (private_project, public_project):
        (project / '.git').mkdir(parents=True)
        (project / '.omh/memory').mkdir(parents=True)
    monkeypatch.chdir(private_project)
    provider, _ = load(public, 'memory-first')
    from gateway.run import _profile_runtime_scope
    from agent.runtime_cwd import set_session_cwd, _SESSION_CWD, resolve_agent_cwd
    from agent.memory_manager import MemoryManager
    with _profile_runtime_scope(public):
        token = set_session_cwd(str(public_project))
        try:
            # Explicit user-store control isolates the independent project-store binding.
            correctly_bound = type(provider)(public_store)
            memory = MemoryManager()
            memory.add_provider(correctly_bound)
            memory.initialize_all('synthetic-public', platform='discord', agent_context='primary')
            row = {'case': 'project-home', 'host_logical_cwd_correct': resolve_agent_cwd() == public_project,
                   'user_store_correct': correctly_bound._omh_home == public_store,
                   'project_store_correct': correctly_bound._project_home == public_project / '.omh',
                   'project_store_follows_process_cwd': correctly_bound._project_home == private_project / '.omh'}
            record(row)
            assert row['host_logical_cwd_correct'] and row['user_store_correct']
            assert row['project_store_correct']
            evidence = importlib.import_module(type(provider).__module__.rsplit('.', 1)[0] + '.tools.evidence_tool')
            assert evidence._project_root({}, {}) == public_project
        finally:
            _SESSION_CWD.reset(token)
