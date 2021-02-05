""" fixtures for this ae namespace portion.
# THIS FILE IS EXCLUSIVELY MAINTAINED IN THE NAMESPACE ROOT PACKAGE. CHANGES HAVE TO BE DONE THERE.
# All changes will be deployed automatically to all the portions of this namespace package.
"""
import os
import sys
import glob
import pytest


SKIP_EXPRESSION = "'CI_PROJECT_ID' in os.environ"
skip_gitlab_ci = pytest.mark.skipif(SKIP_EXPRESSION, reason="headless gitlab CI python 3.6 image lacks window system")


@pytest.fixture
def tst_app_key():
    """ provide value used in tests for AppBase.app_key. """
    return 'pyTstConsAppKey'


@pytest.fixture
def sys_argv_app_key_restore(tst_app_key):          # needed for tests using sys.argv/get_opt() of ConsoleApp
    """ change sys.argv before test run to use test app key and restore sys.argv after test run. """
    old_argv = sys.argv
    sys.argv = [tst_app_key, ]

    yield tst_app_key

    sys.argv = old_argv


@pytest.fixture
def restore_app_env(sys_argv_app_key_restore):
    """ restore app environment after test run - needed for tests instantiating AppBase/ConsoleApp. """
    # LOCAL IMPORT because a portion may not depend-on/use ae.core
    # noinspection PyProtectedMember
    from ae.core import app_inst_lock, _app_instances, _unregister_app_instance

    yield sys_argv_app_key_restore

    # added outer list() because unregister does _app_instances.pop() calls
    # and added inner list() because the .keys() 'generator' object is not reversible
    with app_inst_lock:
        app_keys = list(reversed(list(_app_instances.keys())))
        for key in app_keys:
            # copied from ae.enaml_app conftest.py (not needed for apps based on ae.kivy_app)
            app_instance = _app_instances[key]
            app_win = getattr(app_instance, 'framework_win', False)
            if app_win and hasattr(app_win, 'close') and callable(app_win.close):
                app_win.close()

            # remove app from ae.core app register/dict
            _unregister_app_instance(key)


@pytest.fixture
def cons_app(restore_app_env):
    """ provide ConsoleApp instance that will be unregistered automatically """
    # LOCAL IMPORT because some portions like e.g. ae_core does not depend/use ae.console
    from ae.console import ConsoleApp
    yield ConsoleApp()


@pytest.fixture
def tst_system(cons_app):
    """ CURRENTLY NOT USED """
    from ae.sys_core import SystemBase
    yield SystemBase('Tst', cons_app, dict(User='TstUsr', Password='TstPwd', Dsn='TstDb@TstHost'))


def delete_files(file_name, keep_ext=False, ret_type='count'):
    """ clean up test log files and other test files after test run. """
    if keep_ext:
        fp, fe = os.path.splitext(file_name)
        file_mask = fp + '*' + fe
    else:
        file_mask = file_name + '*'
    cnt = 0
    ret = list()
    for fn in glob.glob(file_mask):
        if ret_type == 'contents':
            with open(fn) as fd:
                fc = fd.read()
            ret.append(fc)
        elif ret_type == 'names':
            ret.append(fn)
        os.remove(fn)
        cnt += 1
    return cnt if ret_type == 'count' else ret
