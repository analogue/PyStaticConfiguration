import contextlib
import gc
import mock
import tempfile
import time
from testify import run, assert_equal, TestCase, setup, teardown, setup_teardown
from testify.assertions import assert_raises
from testify import class_setup, class_teardown

from staticconf import config, errors, testing, proxy
import staticconf


class TestRemoveByKeys(TestCase):

    def test_empty_dict(self):
        keys = range(3)
        assert_equal([], config.remove_by_keys({}, keys))

    def test_no_keys(self):
        keys = []
        map = dict(enumerate(range(3)))
        assert_equal(map.items(), config.remove_by_keys(map, keys))

    def test_overlap(self):
        keys = [1, 3, 5 ,7]
        map = dict(enumerate(range(8)))
        expected = [(0,0), (2, 2), (4, 4), (6, 6)]
        assert_equal(expected, config.remove_by_keys(map, keys))


class ConfigMapTestCase(TestCase):

    @setup
    def setup_config_map(self):
        self.config_map = config.ConfigMap(one=1, three=3, seven=7)

    def test_no_iteritems(self):
        assert not hasattr(self.config_map, 'iteritems')

    def test_getitem(self):
        assert_equal(self.config_map['one'], 1)
        assert_equal(self.config_map['seven'], 7)

    def test_get(self):
        assert_equal(self.config_map.get('three'), 3)
        assert_equal(self.config_map.get('four', 0), 0)

    def test_contains(self):
        assert 'one' in self.config_map
        assert 'two' not in self.config_map

    def test_len(self):
        assert_equal(len(self.config_map), 3)

class ConfigurationNamespaceTestCase(TestCase):

    @setup
    def setup_namespace(self):
        self.name = 'the_name'
        self.namespace = config.ConfigNamespace(self.name)
        self.config_data = dict(enumerate(['one', 'two', 'three'], 1))

    def test_register_get_value_proxies(self):
        proxies = [mock.Mock(), mock.Mock()]
        for mock_proxy in proxies:
            self.namespace.register_proxy(mock_proxy)
        assert_equal(self.namespace.get_value_proxies(), proxies)

    def test_get_value_proxies_does_not_contain_out_of_scope_proxies(self):
        assert not self.namespace.get_value_proxies()
        def a_scope():
            mock_proxy = mock.create_autospec(proxy.ValueProxy)
            self.namespace.register_proxy(mock_proxy)

        a_scope()
        a_scope()
        gc.collect()
        assert_equal(len(self.namespace.get_value_proxies()), 0)

    def test_update_values(self):
        values = dict(one=1, two=2)
        self.namespace.update_values(values)
        assert 'one' in self.namespace
        assert 'two' in self.namespace

    def test_get_config_values(self):
        self.namespace['stars'] = 'foo'
        values = self.namespace.get_config_values()
        assert_equal(values, {'stars': 'foo'})

    def test_get_known_keys(self):
        proxies = [mock.Mock(), mock.Mock()]
        for mock_proxy in proxies:
            self.namespace.register_proxy(mock_proxy)
        expected = set([mock_proxy.config_key for mock_proxy in proxies])
        assert_equal(self.namespace.get_known_keys(), expected)

    def test_validate_keys_no_unknown_keys(self):
        proxies = [mock.Mock(config_key=i) for i in self.config_data]
        for mock_proxy in proxies:
            self.namespace.register_proxy(mock_proxy)
        with mock.patch('staticconf.config.log') as mock_log:
            self.namespace.validate_keys(self.config_data, True)
            self.namespace.validate_keys(self.config_data, False)
            assert not mock_log.warn.mock_calls

    def test_validate_keys_unknown_log(self):
        with mock.patch('staticconf.config.log') as mock_log:
            self.namespace.validate_keys(self.config_data, False)
            assert_equal(len(mock_log.info.mock_calls), 1)

    def test_validate_keys_unknown_raise(self):
        assert_raises(errors.ConfigurationError,
                self.namespace.validate_keys, self.config_data, True)

    def test_clear(self):
        self.namespace.apply_config_data(self.config_data, False, False)
        assert self.namespace.get_config_values()
        self.namespace.clear()
        assert_equal(self.namespace.get_config_values(), {})


class GetNamespaceTestCase(TestCase):

    def test_get_namespace_new(self):
        name = 'some_unlikely_name'
        assert name not in config.configuration_namespaces
        config.get_namespace(name)
        assert name in config.configuration_namespaces

    def test_get_namespace_existing(self):
        name = 'the_common_name'
        namespace = config.get_namespace(name)
        assert_equal(namespace, config.get_namespace(name))


class ReloadTestCase(TestCase):

    @teardown
    def teardown_config(self):
        config._reset()

    def test_reload_default(self):
        staticconf.DictConfiguration(dict(one='three', seven='nine'))
        one, seven = staticconf.get('one'), staticconf.get('seven')

        staticconf.DictConfiguration(dict(one='ten', seven='el'))
        staticconf.reload()
        assert_equal(one, 'ten')
        assert_equal(seven, 'el')

    def test_reload_all(self):
        name = 'another_one'
        staticconf.DictConfiguration(dict(one='three'))
        staticconf.DictConfiguration(dict(two='three'), namespace=name)
        one, two = staticconf.get('one'), staticconf.get('two', namespace=name)
        # access the values to set the value_proxy cache
        one.value, two.value

        staticconf.DictConfiguration(dict(one='four'))
        staticconf.DictConfiguration(dict(two='five'), namespace=name)
        staticconf.reload(all_names=True)
        assert_equal(one, 'four')
        assert_equal(two, 'five')

    def test_reload_single(self):
        name = 'another_one'
        staticconf.DictConfiguration(dict(one='three'))
        staticconf.DictConfiguration(dict(two='three'), namespace=name)
        one, two = staticconf.get('one'), staticconf.get('two', namespace=name)
        # access the values to set the value_proxy cache
        one.value, two.value

        staticconf.DictConfiguration(dict(one='four'))
        staticconf.DictConfiguration(dict(two='five'), namespace=name)
        staticconf.reload()
        assert_equal(one, 'four')
        assert_equal(two, 'three')


class ValidateTestCase(TestCase):

    @teardown
    def teardown_config(self):
        config._reset()

    def test_validate_single_passes(self):
        staticconf.DictConfiguration({})
        config.validate()
        staticconf.get_string('one.two')
        staticconf.DictConfiguration({'one.two': 'nice'})
        config.validate()

    def test_validate_single_fails(self):
        _ = staticconf.get_int('one.two')
        assert_raises(errors.ConfigurationError, config.validate)

    def test_validate_all_passes(self):
        name = 'yan'
        staticconf.DictConfiguration({}, namespace=name)
        staticconf.DictConfiguration({})
        config.validate(all_names=True)
        staticconf.get_string('one.two')
        staticconf.get_string('foo', namespace=name)

        staticconf.DictConfiguration({'one.two': 'nice'})
        staticconf.DictConfiguration({'foo': 'nice'}, namespace=name)
        config.validate(all_names=True)

    def test_validate_all_fails(self):
        name = 'yan'
        _ = staticconf.get_string('foo', namespace=name)
        assert_raises(errors.ConfigurationError, config.validate, all_names=True)


class ViewHelpTestCase(TestCase):

    @class_setup
    def setup_descriptions(self):
        staticconf.get('one', help="the one")
        staticconf.get_time('when', default='NOW', help="The time")
        staticconf.get_bool('you sure', default='No', help='Are you?')
        staticconf.get('one', help="the one", namespace='Beta')
        staticconf.get('one', help="the one", namespace='Alpha')
        staticconf.get('two', help="the two", namespace='Alpha')

    @class_teardown
    def teardown_descriptions(self):
        config._reset()

    @setup
    def setup_lines(self):
        self.lines = config.view_help().split('\n')

        print config.view_help()

    def test_view_help_format(self):
        line, help = self.lines[4:6]
        assert_equal(help, 'The time')
        assert_equal(line, 'when (Type: time, Default: NOW)')

    def test_view_help_format_namespace(self):
        namespace, one, _, two, _, blank = self.lines[9:15]
        assert_equal(namespace, 'Namespace: Alpha')
        assert one.startswith('one')
        assert two.startswith('two')
        assert_equal(blank, '')

    def test_view_help_namespace_sort(self):
        lines = filter(lambda l: l.startswith('Namespace'), self.lines)
        expected = ['Namespace: DEFAULT', 'Namespace: Alpha', 'Namespace: Beta']
        assert_equal(lines, expected)


class HasDuplicateKeysTestCase(TestCase):

    @setup
    def setup_base_conf(self):
        self.base_conf = {'fear': 'is_the', 'mind': 'killer'}

    def test_has_dupliacte_keys_false(self):
        config_data = dict(unique_keys=123)
        assert not config.has_duplicate_keys(config_data, self.base_conf, True)
        assert not config.has_duplicate_keys(config_data, self.base_conf, False)

    def test_has_duplicate_keys_raises(self):
        config_data = dict(fear=123)
        assert_raises(errors.ConfigurationError,
            config.has_duplicate_keys, config_data, self.base_conf, True)

    def test_has_duplicate_keys_no_raise(self):
        config_data = dict(mind=123)
        assert config.has_duplicate_keys(config_data, self.base_conf, False)


class ConfigurationWatcherTestCase(TestCase):

    @setup_teardown
    def setup_mocks_and_config_watcher(self):
        self.loader = mock.Mock()
        with contextlib.nested(
            mock.patch('staticconf.config.time'),
            mock.patch('staticconf.config.os.path'),
            mock.patch('staticconf.config.os.stat'),
            tempfile.NamedTemporaryFile()
        ) as (self.mock_time, self.mock_path, self.mock_stat, file):
            # Create the file
            file.flush()
            self.mock_stat.st_ino=1
            self.mock_stat.st_dev=2
            self.filename = file.name
            self.watcher = config.ConfigurationWatcher(self.loader, self.filename)
            yield

    def test_get_filename_list_from_string(self):
        self.mock_path.abspath.side_effect = lambda p: p
        filename = 'thefilename.yaml'
        filenames = self.watcher.get_filename_list(filename)
        assert_equal(filenames, [filename])

    def test_get_filename_list_from_list(self):
        self.mock_path.abspath.side_effect = lambda p: p
        filenames = ['b', 'g', 'z', 'a']
        expected = ['a', 'b', 'g', 'z']
        assert_equal(self.watcher.get_filename_list(filenames), expected)

    def test_should_check(self):
        self.watcher.last_check = 123456789

        self.mock_time.time.return_value = 123456789
        # Still current, but no min_interval
        assert self.watcher.should_check

        # With max interval
        self.watcher.min_interval = 3
        assert not self.watcher.should_check

        # Time has passed
        self.mock_time.time.return_value = 123456794
        assert self.watcher.should_check

    def test_file_modified_not_modified(self):
        self.watcher.last_check = self.mock_path.getmtime.return_value = 222
        self.mock_time.time.return_value = 123456
        assert not self.watcher.file_modified()
        assert_equal(self.watcher.last_check, self.mock_time.time.return_value)

    def test_file_modified(self):
        self.watcher.last_check = 123456
        self.mock_time.time.return_value = 123460
        self.mock_path.getmtime.return_value = self.watcher.last_check + 5

        assert self.watcher.file_modified()
        assert_equal(self.watcher.last_check, self.mock_time.time.return_value)

    def test_file_modified_moved(self):
        self.watcher.last_check = self.mock_path.getmtime.return_value = 123456
        self.mock_time.time.return_value = 123455
        assert not self.watcher.file_modified()
        self.mock_stat.st_ino = 3
        assert self.watcher.file_modified()

    def test_reload_default(self):
        self.watcher.reload()
        self.loader.assert_called_with()

    def test_reload_custom(self):
        reloader = mock.Mock()
        watcher = config.ConfigurationWatcher(
                self.loader, self.filename, reloader=reloader)
        watcher.reload()
        reloader.assert_called_with()


class ReloadCallbackChainTestCase(TestCase):

    @setup
    def setup_callback_chain(self):
        self.callbacks = list(enumerate([mock.Mock(), mock.Mock()]))
        self.callback_chain = config.ReloadCallbackChain(callbacks=self.callbacks)

    def test_init_with_callbacks(self):
        assert_equal(self.callback_chain.callbacks, dict(self.callbacks))

    def test_add_remove(self):
        callback = mock.Mock()
        self.callback_chain.add('one', callback)
        assert_equal(self.callback_chain.callbacks['one'], callback)
        self.callback_chain.remove('one')
        assert 'one' not in self.callback_chain.callbacks

    def test_call(self):
        self.callback_chain.namespace = 'the_namespace'
        with mock.patch('staticconf.config.reload') as mock_reload:
            self.callback_chain()
            for _, callback in self.callbacks:
                callback.assert_called_with()
                mock_reload.assert_called_with(name='the_namespace', all_names=False)


class ConfigFacadeTestCase(TestCase):

    @setup_teardown
    def patch_watcher(self):
        patcher = mock.patch('staticconf.config.ConfigurationWatcher',
            autospec=True)
        with patcher as self.mock_config_watcher:
            yield

    @setup
    def setup_facade(self):
        self.watcher = mock.create_autospec(config.ConfigurationWatcher)
        self.watcher.get_reloader.return_value = mock.create_autospec(
            config.ReloadCallbackChain)
        self.facade = config.ConfigFacade(self.watcher)

    def test_load(self):
        filename, namespace = "filename", "namespace"
        loader = mock.Mock()
        facade = config.ConfigFacade.load(filename, namespace, loader)
        loader.assert_called_with(filename, namespace=namespace)
        assert_equal(facade.watcher, self.mock_config_watcher.return_value)
        reloader = facade.callback_chain
        assert_equal(reloader, facade.watcher.get_reloader())

    def test_add_callback(self):
        name, func = 'name', mock.Mock()
        self.facade.add_callback(name, func)
        self.facade.callback_chain.add.assert_called_with(name, func)

    def test_reload_if_changed(self):
        self.facade.reload_if_changed()
        self.watcher.reload_if_changed.assert_called_with(force=False)


class ConfigFacadeAcceptanceTest(TestCase):

    _suites = ['acceptance']

    @setup
    def setup_env(self):
        self.file = tempfile.NamedTemporaryFile()
        self.write("""one: A""")

    def write(self, content):
        time.sleep(0.01)
        self.file.file.seek(0)
        self.file.write(content)
        self.file.flush()

    @setup_teardown
    def patch_namespace(self):
        self.namespace = 'testing_namespace'
        with testing.MockConfiguration(namespace=self.namespace):
            yield

    def test_load_end_to_end(self):
        loader = staticconf.YamlConfiguration
        callback = mock.Mock()
        facade = staticconf.ConfigFacade.load(self.file.name, self.namespace, loader)
        facade.add_callback('one', callback)
        assert_equal(staticconf.get('one', namespace=self.namespace), "A")

        self.write("""one: B""")
        facade.reload_if_changed()
        assert_equal(staticconf.get('one', namespace=self.namespace), "B")
        callback.assert_called_with()


if __name__ == "__main__":
    run()
