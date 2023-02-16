""" transfer service unit tests. """
import datetime
import glob
import os
import pytest
import threading
import time
from socket import socket
from unittest.mock import MagicMock

from ae.base import TESTS_FOLDER, os_local_ip
from ae.console import ConsoleApp
from ae.files import read_file_text, write_file_text
from ae.paths import PATH_PLACEHOLDERS

from ae.transfer_service import (
    ENCODING_KWARGS, SERVER_PORT, TRANSFER_KWARGS_LINE_END_BYTE, TRANSFER_KWARGS_LINE_END_CHAR,
    ThreadedTCPRequestHandler, TransferServiceApp,
    clean_log_str, connect_and_request,
    recv_bytes, service_factory, transfer_kwargs_error, transfer_kwargs_from_literal, transfer_kwargs_literal,
    transfer_kwargs_update)


@pytest.fixture
def threaded_server(restore_app_env):
    """ yielding an instantiated and started server app. """
    app = service_factory()
    app.run_app()
    app.start_server(threaded=True)

    yield app

    app.stop_server()


class TestHelpers:
    def test_clean_log_str(self):
        assert clean_log_str("log_str") == "log_str"
        assert clean_log_str("log_str\n") == "log_str"
        assert clean_log_str("log_str\r") == "log_str"
        assert clean_log_str("log_str\\n") == "log_str"
        assert clean_log_str("log_str\\") == "log_str"
        assert clean_log_str("'log_str'") == "log_str"

    def test_clean_log_str_bytes(self):
        assert clean_log_str(b"log_str") == "log_str"
        assert clean_log_str(b"log_str\n") == "log_str"
        assert clean_log_str(b"log_str\r") == "log_str"
        assert clean_log_str(b"log_str\\n") == "log_str"
        assert clean_log_str(b"log_str\\") == "log_str"
        assert clean_log_str(b"'log_str'") == "log_str"

    def test_connect_and_request_server_not_running(self):
        with socket() as sock:
            res = connect_and_request(sock, {})
        assert 'error' in res

    def test_connect_and_request_server_running(self, threaded_server):
        with socket() as sock:
            res = connect_and_request(sock, dict(method_name='pending_requests'))
        assert 'local_ip' in res
        assert res['local_ip'] == os_local_ip()
        assert 'pending_requests' in res
        assert threaded_server.debug == bool(res['pending_requests'])

    def test_recv_bytes(self):
        with socket() as sock:
            with pytest.raises(OSError):
                recv_bytes(sock)

    def test_recv_bytes_server_running(self, threaded_server):
        with socket() as sock:
            sock.connect(('localhost', SERVER_PORT))
            sock.sendall(bytes(transfer_kwargs_literal(dict(method_name='pending_requests')), **ENCODING_KWARGS))
            res = recv_bytes(sock)
            assert res[-1:] == TRANSFER_KWARGS_LINE_END_BYTE
            res = str(res, **ENCODING_KWARGS)
            assert res[-1:] == TRANSFER_KWARGS_LINE_END_CHAR
            res = res[:-1]
            assert res
            res = transfer_kwargs_from_literal(res)
            assert 'pending_requests' in res
            assert threaded_server.debug == bool(res['pending_requests'])

    def test_service_factory(self, restore_app_env):
        app = service_factory()
        assert isinstance(app, ConsoleApp)
        assert app.id_of_task is TransferServiceApp.id_of_task

    def test_service_factory_id_of_task_patch(self, restore_app_env):
        def _id_of_task(act, obj, key):
            return act + "_" + obj + ":" + key
        app = service_factory(task_id_func=_id_of_task)
        assert app.id_of_task is _id_of_task

    def test_transfer_kwargs_error(self):
        kwargs = {}
        err_msg = "1st err"
        transfer_kwargs_error(kwargs, err_msg)
        assert 'error' in kwargs
        assert err_msg in kwargs['error']

        err_msg = "new err"
        transfer_kwargs_error(kwargs, err_msg)
        assert 'error' in kwargs
        assert err_msg in kwargs['error']

    def test_transfer_service_from_literal_basics(self):
        assert transfer_kwargs_from_literal("{}") == {}

    def test_transfer_service_from_literal_date_time(self):
        assert transfer_kwargs_from_literal("{'x_date': (1999, 1, 10)}") == dict(x_date=datetime.datetime(1999, 1, 10))
        assert transfer_kwargs_from_literal("{'_date': (1999, 1, 10)}") == dict(_date=datetime.datetime(1999, 1, 10))

    def test_transfer_kwargs_literal_basics(self):
        assert transfer_kwargs_literal({}) == "{}" + TRANSFER_KWARGS_LINE_END_CHAR

    def test_transfer_kwargs_literal_date_time(self):
        test_time = datetime.datetime.now()
        assert transfer_kwargs_literal(dict(y_time=test_time)) == \
               "{'y_time': " + str(tuple(test_time.timetuple())[:7]) + "}" + TRANSFER_KWARGS_LINE_END_CHAR
        assert transfer_kwargs_literal(dict(_time=test_time)) == \
               "{'_time': " + str(tuple(test_time.timetuple())[:7]) + "}" + TRANSFER_KWARGS_LINE_END_CHAR

    def test_transfer_kwargs_update(self):
        kwargs = {}
        kwargs2 = {}
        new_val = "new_val"
        transfer_kwargs_update(kwargs, kwargs2, new_key=new_val)
        assert 'new_key' in kwargs
        assert kwargs['new_key'] == new_val
        assert 'new_key' in kwargs2
        assert kwargs2['new_key'] == new_val


class TestThreadedTCPRequestHandler:
    def test_handle_exception(self):
        request = MagicMock()
        client_address = MagicMock()
        server = MagicMock()
        ThreadedTCPRequestHandler(request, client_address, server)


class TestTransferServiceApp:
    def test_cancel_request(self, threaded_server):
        rt_id = "rt_id"
        threaded_server.reqs_and_logs.append(dict(rt_id=rt_id))
        req = dict(rt_id_to_cancel=rt_id)
        res = threaded_server.cancel_request(req, MagicMock())
        assert 'error' not in res
        assert threaded_server.reqs_and_logs
        idx = -2 if threaded_server.debug else -1
        assert threaded_server.reqs_and_logs[idx]['rt_id'] == rt_id
        assert threaded_server.reqs_and_logs[idx]['error']
        assert req['completed'] is True

    def test_cancel_request_error(self, threaded_server):
        rt_id = "rt_id"
        threaded_server.reqs_and_logs.append(dict(rt_id=rt_id))
        req = dict(rt_id_to_cancel=rt_id + " to make it fail")
        res = threaded_server.cancel_request(req, MagicMock())
        assert 'error' in res
        assert threaded_server.reqs_and_logs
        idx = -2 if threaded_server.debug else -1
        assert threaded_server.reqs_and_logs[idx]['rt_id'] == rt_id
        assert 'error' not in threaded_server.reqs_and_logs[idx]
        assert 'completed' not in req

    def test_id_of_task(self, threaded_server):
        assert threaded_server.id_of_task('action', 'object', 'key')
        assert 'action' in threaded_server.id_of_task('action', 'object', 'key')
        assert 'object' in threaded_server.id_of_task('action', 'object', 'key')
        assert 'key' in threaded_server.id_of_task('action', 'object', 'key')

    def test_log_out_method(self, threaded_server):
        def _out(*args):
            nonlocal called
            called = args
        called = ()
        setattr(threaded_server, 'tst_out', _out)

        msg = "message"
        threaded_server.log('tst', msg)
        assert called
        assert msg in called[0]

    def test_log_append(self, threaded_server):
        rt_id_part = "ijk"
        assert threaded_server.debug == bool(threaded_server.reqs_and_logs)
        threaded_server.log(rt_id_part, "message")
        assert len(threaded_server.reqs_and_logs) == 2 if threaded_server.debug else 1
        req = threaded_server.reqs_and_logs[-1]
        assert req['method_name'] == rt_id_part + "_log"
        assert req['message'] == "message"
        assert req['completed'] is True
        assert req['log_time']
        assert rt_id_part in req['rt_id']

    def test_pending_requests(self, threaded_server):
        rt_id = "rt_id"
        rt_req = dict(rt_id=rt_id)
        threaded_server.reqs_and_logs.append(rt_req)
        req = {}
        res = threaded_server.pending_requests(req, MagicMock())
        assert 'error' not in res
        assert threaded_server.reqs_and_logs[0]['rt_id'] == rt_id
        assert threaded_server.reqs_and_logs[0] is rt_req
        assert req['pending_requests'][-1] == rt_req

    def test_pending_requests_with_error_removed(self, threaded_server):
        rt_id = "rt_id"
        rt_req = dict(rt_id=rt_id, error="error")
        threaded_server.reqs_and_logs.append(rt_req)
        req = {}
        res = threaded_server.pending_requests(req, MagicMock())
        assert 'error' not in res
        assert not threaded_server.reqs_and_logs
        assert res['pending_requests'][-1] == rt_req

    def test_pending_requests_with_completed_removed(self, threaded_server):
        rt_id = "rt_id"
        rt_req = dict(rt_id=rt_id, completed=True)
        threaded_server.reqs_and_logs.append(rt_req)
        req = {}
        res = threaded_server.pending_requests(req, MagicMock())
        assert 'error' not in res
        assert not threaded_server.reqs_and_logs
        assert res['pending_requests'][-1] == rt_req

    def test_recv_file_not_found(self, threaded_server):
        req = dict(file_path="not_exists.tst", total_bytes=333)
        PATH_PLACEHOLDERS['downloads'] = 'downloads_path'
        res = threaded_server.recv_file(req, MagicMock())
        assert 'error' in res
        assert threaded_server.debug == bool(threaded_server.reqs_and_logs)

    def test_recv_file_zero_len(self, threaded_server):
        req = dict(file_path="not_exists.xxx", total_bytes=0)
        PATH_PLACEHOLDERS['downloads'] = TESTS_FOLDER
        res = threaded_server.recv_file(req, MagicMock())
        assert 'error' in res
        assert threaded_server.debug == bool(threaded_server.reqs_and_logs)

    def test_recv_file_series(self, threaded_server):
        file_name = "tests/conftest.py"
        with open(file_name, 'rb') as fp:
            req = dict(file_path="conftest.py", total_bytes=os.fstat(fp.fileno()).st_size, series_file=True)
            PATH_PLACEHOLDERS['downloads'] = TESTS_FOLDER
            handler = MagicMock()
            handler.rfile = fp
            res = threaded_server.recv_file(req, handler)
        assert 'error' not in res
        assert threaded_server.debug == bool(threaded_server.reqs_and_logs)
        assert os.path.exists(res['series_file_name'])
        assert read_file_text(file_name) == read_file_text(res['series_file_name'])
        os.remove(res['series_file_name'])

    def test_recv_file_folder_no_file(self, threaded_server):
        req = dict(file_path="tests", total_bytes=333)
        PATH_PLACEHOLDERS['downloads'] = '.'
        res = threaded_server.recv_file(req, MagicMock())
        assert 'error' in res
        assert threaded_server.debug == bool(threaded_server.reqs_and_logs)

    def test_recv_file(self, threaded_server):
        with open("tests/conftest.py", 'rb') as fp:
            req = dict(file_path="conftest.py", total_bytes=os.fstat(fp.fileno()).st_size)
            PATH_PLACEHOLDERS['downloads'] = TESTS_FOLDER
            handler = MagicMock()
            handler.rfile = fp
            res = threaded_server.recv_file(req, handler)
        assert 'error' in res   # already transferred
        assert threaded_server.reqs_and_logs

    def test_recv_message(self, threaded_server):
        msg = "message"
        req = dict(message=msg)
        res = threaded_server.recv_message(req, MagicMock())
        assert 'transferred_bytes' in res
        assert res['transferred_bytes'] == len(msg)
        assert 'error' not in res

    def test_response_to_request_pending_requests(self, threaded_server):
        req = dict(method_name='pending_requests')
        res_lit = threaded_server.response_to_request(transfer_kwargs_literal(req), MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' not in res

    def test_response_to_request_recv_message(self, threaded_server):
        msg = "message"
        req = dict(method_name='recv_message', message=msg)
        res_lit = threaded_server.response_to_request(transfer_kwargs_literal(req), MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' not in res

    def test_response_to_request_recv_message_completed(self, threaded_server):
        msg = "message"
        req = dict(method_name='recv_message', message=msg, total_bytes=len(msg))
        res_lit = threaded_server.response_to_request(transfer_kwargs_literal(req), MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' not in res

    def test_response_to_request_err_invalid_lit(self, threaded_server):
        res_lit = threaded_server.response_to_request("{xxx", MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' in res

    def test_response_to_request_err_empty_res(self, threaded_server):
        req = dict(method_name='patched_meth')
        setattr(threaded_server, 'patched_meth', lambda *_args, **_kwargs: {})
        res_lit = threaded_server.response_to_request(transfer_kwargs_literal(req), MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' in res

    def test_response_to_request_err_in_req(self, threaded_server):
        req = dict(method_name='patched_meth', error="req_error")
        setattr(threaded_server, 'patched_meth', lambda *_args, **_kwargs: dict(something="xxx"))
        res_lit = threaded_server.response_to_request(transfer_kwargs_literal(req), MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' in res
        assert threaded_server.reqs_and_logs[-1]['method_name'] == 'patched_meth'
        assert threaded_server.reqs_and_logs[-1]['error'] == "req_error"

    def test_response_to_request_err_in_res(self, threaded_server):
        req = dict(method_name='patched_meth')
        setattr(threaded_server, 'patched_meth', lambda *_args, **_kwargs: dict(error="res_error"))
        res_lit = threaded_server.response_to_request(transfer_kwargs_literal(req), MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' in res
        assert threaded_server.reqs_and_logs[-1]['method_name'] == 'patched_meth'
        assert threaded_server.reqs_and_logs[-1]['error'] == "res_error"
        assert res['error'] == "res_error"

    def test_send_file(self, threaded_server):
        file_content = "content"
        file_len = len(file_content)
        file_path = "tests/send_test.test"
        write_file_text(file_content, file_path)
        req = dict(file_path=file_path, local_ip=os_local_ip(), remote_ip=os_local_ip(), total_bytes=file_len)
        res = threaded_server.send_file(req, MagicMock())
        assert 'transferred_bytes' in res
        assert res['transferred_bytes'] == file_len
        assert res['file_path'] == '{downloads}/send_test.test'  # != file_path
        assert 'error' not in res
        time.sleep(3.0)
        for file_name in glob.glob("tests/send_test*.test"):
            os.remove(file_name)

    def test_send_file_already_transferred(self, threaded_server):
        file_path = "tests/conftest.py"
        with open(file_path, 'rb') as fp:
            file_len = os.fstat(fp.fileno()).st_size
        req = dict(file_path=file_path, local_ip=os_local_ip(), remote_ip='localhost', total_bytes=file_len)
        res = threaded_server.send_file(req, MagicMock())
        assert 'transferred_bytes' in res
        assert res['transferred_bytes']
        assert res['file_path'] == '{downloads}/conftest.py'  # file_path
        assert 'error' in res

    def test_send_file_not_existing(self, threaded_server):
        file_path = "zzz.y"
        req = dict(file_path=file_path, local_ip=os_local_ip(), remote_ip='localhost', total_bytes=111)
        res = threaded_server.send_file(req, MagicMock())
        assert 'transferred_bytes' not in res
        assert 'error' in res

    def test_send_file_empty(self, threaded_server):
        file_path = "tests/test_send_file.zzz"
        write_file_text("", file_path)
        req = dict(file_path=file_path, local_ip=os_local_ip(), remote_ip='localhost', total_bytes=0)
        res = threaded_server.send_file(req, MagicMock())
        assert 'transferred_bytes' in res
        assert not res['transferred_bytes']
        assert 'error' in res
        assert os.path.exists(file_path)
        os.remove(file_path)

    def test_send_message(self, threaded_server):
        msg = "message"
        req = dict(message=msg, local_ip=os_local_ip(), remote_ip='localhost')  # os_local_ip())
        res = threaded_server.send_message(req, MagicMock())
        assert 'transferred_bytes' in res
        assert res['transferred_bytes'] == len(msg)
        assert res['message'] == msg
        assert 'error' not in res

    def test_start_server(self, restore_app_env):
        app = service_factory()
        thread = threading.Thread(target=app.start_server)
        thread.start()
        while not getattr(app, 'server_instance', False) and not getattr(app, 'server_thread', False):
            pass
        app.stop_server()

    def test_start_server_exception(self, restore_app_env):
        app = service_factory()
        app.run_app()
        app.set_opt('bind', ":invalid bind address:", save_to_config=False)
        app.set_opt('port', ":invalid port:", save_to_config=False)
        assert app.start_server(threaded=True)
