"""Assertions express required safety; expected failures identify candidate gaps."""
import importlib.util
import importlib
import json
from pathlib import Path
import shutil
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('review_baseline', REPO / 'tests/native/test_profile_runtime.py')
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
fixture = baseline.fixture


def core():
    sys.path.insert(0, str(REPO / 'src'))
    import omh
    assert Path(omh.__file__).resolve().is_relative_to(REPO)


def settings(home, values):
    path = home / 'config.yaml'
    config = {'memory': {'provider': 'omh'}, 'plugins': {'enabled': ['omh'],
              'entries': {'omh': {'settings': values}}}, 'terminal': {'backend': 'local'}}
    path.write_text(json.dumps(config))


@pytest.mark.parametrize('level', ['settings', 'entry'])
def test_managed_null_section_preserves_native_winner(fixture, monkeypatch, level):
    root, public, private_store, public_store = fixture
    core()
    settings(public, {'omh_home': str(public_store)})
    entry = {'settings': None} if level == 'settings' else None
    managed = root.parent / 'null-managed'
    managed.mkdir()
    (managed / 'config.yaml').write_text(json.dumps({'plugins': {'entries': {'omh': entry}}}))
    monkeypatch.setenv('HERMES_MANAGED_DIR', str(managed))
    from gateway.run import _profile_runtime_scope
    from hermes_cli.config import load_config_readonly
    from omh.plugin_bundle.omh.runtime_paths import resolve_homes
    with _profile_runtime_scope(public):
        effective = load_config_readonly()['plugins']['entries']['omh']['settings']['omh_home']
        assert effective == str(public_store)
        assert resolve_homes() == (public_store, public)
    provider, manager = baseline.load(public, 'general-first')
    assert manager._plugins['omh'].enabled
    assert manager._plugins['omh'].error is None
    assert provider._omh_home == public_store


def observed(**row):
    print('REVIEW_OBSERVED=' + json.dumps(row, sort_keys=True))


@pytest.mark.parametrize('binding', ['relative', 'absolute'])
def test_relative_observer_binding(fixture, monkeypatch, binding):
    root, public, private_store, public_store = fixture
    core()
    launch = root.parent / 'private-project'
    launch.mkdir()
    monkeypatch.chdir(launch)
    value = 'state' if binding == 'relative' else str(public_store)
    settings(public, {'omh_home': value, 'group_chat_activity': {'enabled': True}})
    provider, manager = baseline.load(public, 'general-first')
    intended = public / 'state' if binding == 'relative' else public_store
    wrong = launch / 'state'
    observed(case='relative-observer', binding=binding, provider_home=str(provider._omh_home),
             intended=str(intended),
             foreign_files=[str(p.relative_to(wrong)) for p in wrong.rglob('*') if p.is_file()],
             intended_files=[str(p.relative_to(intended)) for p in intended.rglob('*') if p.is_file()])
    assert provider._omh_home == intended
    assert not list(wrong.rglob('*.key')), 'observer keys must use the same configured root as the provider'
    assert list((intended / 'runtime/group-activity-keys').glob('*.key'))


def test_foreign_scope_manager_registration(fixture):
    root, public, private_store, public_store = fixture
    core()
    settings(public, {'group_chat_activity': {'enabled': True}})  # legacy scoped .env remains present
    from gateway.run import _profile_runtime_scope
    from hermes_cli.plugins import get_plugin_manager
    from hermes_constants import get_hermes_home
    from agent.secret_scope import get_secret
    with _profile_runtime_scope(public):
        manager = get_plugin_manager()
    with _profile_runtime_scope(root):
        manager.discover_and_load()  # real manager supplies only its immutable home override
        assert get_hermes_home() == root  # native token reset remains correct
        assert get_secret('OMH_HOME') == str(private_store)
    foreign_keys = list((private_store / 'runtime/group-activity-keys').glob('*.key'))
    expected_keys = list((public_store / 'runtime/group-activity-keys').glob('*.key'))
    observed(case='partial-manager-scope', manager_home=str(manager.home_path),
             foreign_keys=[p.name for p in foreign_keys], public_keys=[p.name for p in expected_keys],
             loaded=[{'key':k, 'enabled':v.enabled, 'error':v.error} for k,v in manager._plugins.items()])
    assert not foreign_keys, 'public manager registration must not consume the caller profile secret scope'
    if not expected_keys:
        # An anonymous foreign scope may be refused instead of rebound. Either
        # outcome must precede all observer IO and disable the failed plugin.
        failed = manager._plugins['omh']
        assert not failed.enabled and failed.error
        assert not manager._hooks.get('on_room_member_activity')


def test_untrusted_path_cannot_read_scoped_token(fixture, monkeypatch):
    root, public, private_store, public_store = fixture
    marker = 'SYNTHETIC_TOKEN_NOT_FOR_TOOL_OUTPUT'
    monkeypatch.chdir(root.parent)
    monkeypatch.delenv('REVIEW_ONLY_API_TOKEN', raising=False)
    (public / '.env').write_text(f'OMH_HOME={public_store}\nREVIEW_ONLY_API_TOKEN={marker}\n')
    provider, manager = baseline.load(public, 'general-first')
    from gateway.run import _profile_runtime_scope
    from tools.registry import registry
    with _profile_runtime_scope(public):
        result = registry.get_entry('omh_gather_evidence').handler(
            {'commands': ['git diff --check'], 'project_root': '$REVIEW_ONLY_API_TOKEN'})
    from agent.redact import redact_sensitive_text
    scrubbed = redact_sensitive_text(result, force=True)
    observed(case='untrusted-path-token', returned_marker=marker in result,
             survives_native_redactor=marker in scrubbed, result=json.loads(result))
    assert marker not in result, 'model path text must not become a credential-read API'


@pytest.mark.parametrize('order', ['general-first', 'memory-first'])
@pytest.mark.parametrize('profile_order', ['private-first', 'public-first'])
def test_shared_source_reload_controls(fixture, monkeypatch, order, profile_order):
    root, public, private_store, public_store = fixture
    core()
    shared = root.parent / 'shared-omh'
    shutil.copytree(baseline.BUNDLE, shared, ignore=shutil.ignore_patterns('__pycache__'))
    for home in (root, public):
        shutil.rmtree(home / 'plugins/omh')
        (home / 'plugins/omh').symlink_to(shared, target_is_directory=True)
    homes = (root, public) if profile_order == 'private-first' else (public, root)
    loaded = {home: baseline.load(home, order) for home in homes}
    from gateway.run import _profile_runtime_scope
    from tools.registry import registry
    rows = []
    for cycle in range(2):
        for home, store in ((root, private_store), (public, public_store)):
            with _profile_runtime_scope(home):
                old_provider, manager = loaded[home]
                assert old_provider._omh_home == store
                if cycle:
                    assert manager.unload('omh')
                    manager.discover_and_load(force=True)
                assert len(manager._hooks['on_session_end']) == 1
                result = json.loads(registry.get_entry('omh_todo').handler(
                    {'action': 'set', 'title': 'review-'+store.name,
                     'items': [{'text': 'synthetic', 'state': 'pending'}]}, session_id='same-session'))
                assert result['status'] == 'written'
                rows.append({'cycle':cycle, 'home':str(home), 'provider_home':str(old_provider._omh_home),
                             'session_hooks':len(manager._hooks['on_session_end'])})
    observed(case='shared-source-reload', order=order, profile_order=profile_order, rows=rows)


def test_native_single_owner_unscoped_startup(fixture, monkeypatch):
    root, public, private_store, public_store = fixture
    core()
    from agent.secret_scope import set_multiplex_active, set_secret_scope, reset_secret_scope
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from plugins.memory import load_memory_provider
    from hermes_cli.plugins import get_plugin_manager
    set_multiplex_active(False)
    ht, st = set_hermes_home_override(None), set_secret_scope(None)
    try:
        manager = get_plugin_manager()
        manager.discover_and_load()
        provider = load_memory_provider('omh', register_skills=False)
        assert provider is not None and provider._omh_home == private_store
        from tools.registry import registry
        result = json.loads(registry.get_entry('omh_todo').handler({'action':'show'}))
        observed(case='single-owner-unscoped', provider_home=str(provider._omh_home), tool_returned=bool(result))
    finally:
        reset_secret_scope(st)
        reset_hermes_home_override(ht)


def test_bound_provider_work_under_foreign_scope(fixture):
    root, public, private_store, public_store = fixture
    provider, manager = baseline.load(public, 'memory-first')
    blocks = importlib.import_module(type(provider).__module__.rsplit('.', 1)[0] + '.memory_blocks')
    block = blocks.build_memory_block(label='review-positive', value='SYNTHETIC_PUBLIC_BOUND_RECALL',
        description='Synthetic independent review control', tier='system')
    blocks.write_memory_block(public_store, blocks.approve_memory_block(block, reviewer_claim='user'))
    from gateway.run import _profile_runtime_scope
    with _profile_runtime_scope(public):
        provider.initialize('review-bound', hermes_home=public, cwd=public, platform='cli')
    before = baseline.snapshot(private_store)
    with _profile_runtime_scope(root):
        provider.on_turn_start(1, 'Synthetic public queued work')
        provider.queue_prefetch('Synthetic public queued work', session_id='review-bound')
        text = provider.prefetch(session_id='review-bound')
    assert 'SYNTHETIC_PUBLIC_BOUND_RECALL' in text
    assert baseline.snapshot(private_store) == before
    assert (public_store / 'memory/dreaming.json').exists()
    observed(case='bound-provider-foreign-scope', positive_recall=True, foreign_store_unchanged=True)


def test_managed_absolute_override_beats_user_template(fixture, monkeypatch):
    root, public, private_store, public_store = fixture
    core()
    settings(public, {'omh_home': '$HERMES_HOME/user-state'})
    managed = root.parent / 'admin-config'
    managed.mkdir()
    (managed / 'config.yaml').write_text(json.dumps({'plugins': {'entries': {'omh': {
        'settings': {'omh_home': str(public_store)}}}}}))
    monkeypatch.setenv('HERMES_MANAGED_DIR', str(managed))
    from gateway.run import _profile_runtime_scope
    from hermes_cli.config import load_config_readonly
    from omh.plugin_bundle.omh.runtime_paths import resolve_homes
    with _profile_runtime_scope(public):
        effective = load_config_readonly()['plugins']['entries']['omh']['settings']['omh_home']
        assert effective == str(public_store)
        try:
            actual = resolve_homes()
        except Exception as exc:
            observed(case='managed-absolute-override', effective=effective, error_type=type(exc).__name__, error=str(exc))
            raise
        assert actual == (public_store, public)


def test_missing_deleted_project_context_controls(fixture, monkeypatch):
    root, public, private_store, public_store = fixture
    core()
    launch = root.parent / 'launch-project'
    (launch / '.git').mkdir(parents=True)
    monkeypatch.chdir(launch)
    provider, _ = baseline.load(public, 'memory-first')
    from gateway.run import _profile_runtime_scope
    from agent.runtime_cwd import set_session_cwd, _SESSION_CWD
    base = type(provider).__module__.rsplit('.', 1)[0]
    paths = importlib.import_module(base + '.runtime_paths')
    evidence = importlib.import_module(base + '.tools.evidence_tool')
    from omh.paths import find_project_root
    from tools.terminal_scope import set_terminal_scope, reset_terminal_scope
    for value in ('', str(public / 'deleted-project')):
        with _profile_runtime_scope(public):
            token = set_session_cwd(value)
            terminal_token = set_terminal_scope({'TERMINAL_CWD': ''})
            try:
                provider.initialize('review-project', hermes_home=public, platform='cli')
                assert provider._project_home is None
                assert find_project_root() is None
                with pytest.raises(paths.RuntimeBindingError):
                    evidence._project_root({}, {})
            finally:
                reset_terminal_scope(terminal_token)
                _SESSION_CWD.reset(token)
    observed(case='missing-deleted-project', provider_has_project=provider._project_home is not None)

@pytest.mark.parametrize('field', ['project_root', 'workdir'])
@pytest.mark.parametrize('reference', ['$REVIEW_ONLY_API_TOKEN', '${REVIEW_ONLY_API_TOKEN}', '${env:REVIEW_ONLY_API_TOKEN}', '%REVIEW_ONLY_API_TOKEN%'])
def test_evidence_input_variables_refused_before_lookup(fixture, monkeypatch, field, reference):
    root, public, private_store, public_store = fixture
    provider, _ = baseline.load(public, 'general-first')
    from gateway.run import _profile_runtime_scope
    from tools.registry import registry
    base = type(provider).__module__.rsplit('.', 1)[0]
    paths = importlib.import_module(base + '.runtime_paths')
    # Fail if the input crosses into credential resolution, even if redacted.
    def forbidden(*args, **kwargs):
        pytest.fail('untrusted input performed a credential lookup')
    monkeypatch.setattr(paths, '_profile_variable', forbidden)
    with _profile_runtime_scope(public):
        result = json.loads(registry.get_entry('omh_gather_evidence').handler(
            {'commands': ['git diff --check'], 'project_root': str(public), field: reference}))
    assert result['error'] == 'OMH input paths do not support variable references'
    assert 'results' not in result


@pytest.mark.parametrize('feature', ['egress_attempts', 'browser_bridge'])
@pytest.mark.parametrize('binding', ['scoped-env', 'foreign-scope', 'relative-setting', 'explicit-feature'])
def test_optional_sibling_registration_owner(fixture, monkeypatch, feature, binding):
    from inspect import getclosurevars
    from gateway.run import _profile_runtime_scope
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli.plugins import get_plugin_manager, PluginContext, PluginManifest
    root, public, private_store, public_store = fixture
    core()
    settings(public, {'omh_home': 'state'} if binding == 'relative-setting' else {})
    with _profile_runtime_scope(public):
        manager = get_plugin_manager()
        ctx = PluginContext(PluginManifest(name='omh', key='omh'), manager)
    module = importlib.import_module('omh.plugin_bundle.omh.' + feature)
    paths = importlib.import_module('omh.plugin_bundle.omh.runtime_paths')
    config = {'omh_home': str(public_store / 'feature')} if binding == 'explicit-feature' else {}
    expected = (public / 'state' if binding == 'relative-setting' else
                public_store / 'feature' if binding == 'explicit-feature' else public_store)
    before = baseline.snapshot(private_store)
    with _profile_runtime_scope(root if binding == 'foreign-scope' else public):
        token = set_hermes_home_override(str(public))  # native manager's home-only transition
        try:
            if binding == 'foreign-scope':
                with pytest.raises(paths.RuntimeBindingError, match='ownership is unverified'):
                    module.register(ctx, config)
                assert not manager._hooks
            elif feature == 'egress_attempts':
                module.register(ctx, config)
                assert manager._hooks['pre_tool_call'][0].__self__.home == expected
            else:
                module.register(ctx, config)
                # Inspect the bound store, without pretending to authorize a
                # browser task or providing a fake native admission identity.
                end = manager._hooks['on_session_end'][0]
                get_manager = getclosurevars(end).nonlocals['get_manager']
                assert getclosurevars(get_manager).nonlocals['home'] == expected
        finally:
            reset_hermes_home_override(token)
    assert baseline.snapshot(private_store) == before


def test_native_launch_owner_empty_scope_overlay(fixture):
    from gateway.run import _profile_runtime_scope
    from agent.secret_scope import set_multiplex_active
    root, public, private_store, public_store = fixture
    core()
    from omh.plugin_bundle.omh.runtime_paths import resolve_homes
    settings(root, {})
    (root / '.env').write_text('')
    set_multiplex_active(False)
    with _profile_runtime_scope(root):
        assert resolve_homes() == (private_store, root)


@pytest.mark.parametrize('managed_kind', ['unrelated-leaf', 'legacy-shadowed', 'ambiguous-winning'])
def test_managed_winning_source_controls(fixture, monkeypatch, managed_kind):
    from gateway.run import _profile_runtime_scope
    root, public, private_store, public_store = fixture
    core()
    from omh.plugin_bundle.omh.runtime_paths import resolve_homes, RuntimeBindingError
    settings(public, {'omh_home': '$HERMES_HOME/state'})
    entry = {'settings': {'enabled': True}}
    if managed_kind == 'legacy-shadowed':
        entry = {'config': {'omh_home': str(private_store)}}
    elif managed_kind == 'ambiguous-winning':
        settings(public, {'omh_home': str(public_store)})
        entry = {'settings': {'omh_home': '${HERMES_HOME}/state'}}
    managed = root.parent / 'managed'
    managed.mkdir()
    (managed / 'config.yaml').write_text(json.dumps({'plugins': {'entries': {'omh': entry}}}))
    monkeypatch.setenv('HERMES_MANAGED_DIR', str(managed))
    with _profile_runtime_scope(public):
        if managed_kind == 'ambiguous-winning':
            with pytest.raises(RuntimeBindingError, match='expansion disagrees'):
                resolve_homes()
        else:
            assert resolve_homes() == (public / 'state', public)
