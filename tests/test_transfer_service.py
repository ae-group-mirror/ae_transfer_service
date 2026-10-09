""" transfer service unit tests. """
import datetime
import os
import time

import pytest
import threading

from socket import socket
from unittest.mock import MagicMock, mock_open, patch

from ae.base import os_path_isfile, os_path_join, write_file
from ae.system import os_local_ip
from ae.files import read_file_text, write_file_text
from ae.paths import PATH_PLACEHOLDERS
from ae.core import DEBUG_LEVEL_ENABLED, DEBUG_LEVEL_VERBOSE
from ae.console import ConsoleApp


from ae.transfer_service import (
    ENCODING_KWARGS, SERVER_PORT, SOCKET_BUF_LEN, TRANSFER_KWARGS_LINE_END_BYTE, TRANSFER_KWARGS_LINE_END_CHAR,
    ThreadedTCPRequestHandler, TransferKwargs, TransferServiceApp,
    clean_log_str, connect_and_request, recv_bytes, requests_lock, service_factory,
    transfer_kwargs_error, transfer_kwargs_from_literal, transfer_kwargs_literal, transfer_kwargs_update)


@pytest.fixture
def threaded_server(restore_app_env):
    """ yielding an instantiated and started server app. """
    app = service_factory()
    app.set_option('port', 0, save_to_config=False)  # let the OS choose a free/unused port number
    app.run_app()
    app.start_server(threaded=True)

    yield app

    app.stop_server()
    assert app.server_instance is None     # sanity check: is the new instance really fully&correctly cleared
    assert app.server_thread is None


class TestHelpers:
    def test_clean_log_str(self):
        assert clean_log_str("log_str") == "log_str"
        assert clean_log_str("log_str\n") == "log_str"
        assert clean_log_str("log_str\r") == "log_str"
        assert clean_log_str("log_str\\n") == "log_str"
        assert clean_log_str("log_str\\r") == "log_str"
        assert clean_log_str("log_str\\") == "log_str"
        assert clean_log_str("'log_str'") == "log_str"

    def test_clean_log_str_bytes(self):
        assert clean_log_str(b"log_str") == "log_str"
        assert clean_log_str(b"log_str\n") == "log_str"
        assert clean_log_str(b"log_str\r") == "log_str"
        assert clean_log_str(b"log_str\\n") == "log_str"
        assert clean_log_str(b"log_str\\r") == "log_str"
        assert clean_log_str(b"log_str\\") == "log_str"
        assert clean_log_str(b"'log_str'") == "log_str"

    def test_connect_and_request_server_not_running(self):
        with socket() as sock:
            res = connect_and_request(sock, {})
        assert 'error' in res

    def test_connect_and_request_server_running(self, threaded_server):
        with socket() as sock:
            res = connect_and_request(sock, {'method_name': 'pending_requests'})
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
            sock.sendall(bytes(transfer_kwargs_literal({'method_name': 'pending_requests'}), **ENCODING_KWARGS))

            res = recv_bytes(sock)

            assert res[-1:] == TRANSFER_KWARGS_LINE_END_BYTE
            res = str(res, **ENCODING_KWARGS)
            assert res[-1:] == TRANSFER_KWARGS_LINE_END_CHAR
            res = res[:-1]
            assert res
            res = transfer_kwargs_from_literal(res)
            assert 'pending_requests' in res
            assert threaded_server.debug == bool(res['pending_requests'])

    def test_recv_bytes_empty_chunk_err(self):
        recv = MagicMock(return_value=b"")
        sock = MagicMock(recv=recv)
        app = MagicMock()
        app.vpo = MagicMock()
        with patch('ae.transfer_service.server_app', app):
            res = recv_bytes(sock)

            assert b'empty chunk' in res

            recv.assert_called_once_with(SOCKET_BUF_LEN)
            app.vpo.assert_called()

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
        assert transfer_kwargs_from_literal("{'x_date': (1999, 1, 10)}") == {'x_date': datetime.datetime(1999, 1, 10)}
        assert transfer_kwargs_from_literal("{'_date': (1999, 1, 10)}") == {'_date': datetime.datetime(1999, 1, 10)}

    def test_transfer_kwargs_literal_basics(self):
        assert transfer_kwargs_literal({}) == "{}" + TRANSFER_KWARGS_LINE_END_CHAR

    def test_transfer_kwargs_literal_date_time(self):
        test_time = datetime.datetime.now()
        # noinspection PyTypeChecker
        assert transfer_kwargs_literal({'y_time': test_time}) == \
               "{'y_time': " + str(tuple(test_time.timetuple())[:7]) + "}" + TRANSFER_KWARGS_LINE_END_CHAR
        # noinspection PyTypeChecker
        assert transfer_kwargs_literal({'_time': test_time}) == \
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
        threaded_server.reqs_and_logs.append({'rt_id': rt_id})
        req = {'rt_id_to_cancel': rt_id}
        res = threaded_server.cancel_request(req, MagicMock())
        assert 'error' not in res
        assert threaded_server.reqs_and_logs
        idx = -2 if threaded_server.debug else -1
        assert threaded_server.reqs_and_logs[idx]['rt_id'] == rt_id
        assert threaded_server.reqs_and_logs[idx]['error']
        assert req['completed'] is True

    def test_cancel_request_error(self, threaded_server):
        rt_id = "rt_id"
        threaded_server.reqs_and_logs.append({'rt_id': rt_id})
        req = {'rt_id_to_cancel': rt_id + " to make it fail"}
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

    def test_log(self, threaded_server):
        called: tuple[str, ...] = ()

        def _out(*args):
            nonlocal called
            called = args
        setattr(threaded_server, 'tst_out', _out)

        msg = "message"
        threaded_server.log('tst', msg)
        assert len(called) > 0
        assert msg in called[0]

    def test_log_append(self, capsys, threaded_server):
        rt_id_part = "any_but_'print'_'debug'_or_'verbose'"
        assert threaded_server.debug == bool(threaded_server.reqs_and_logs)
        log_len = len(threaded_server.reqs_and_logs)

        threaded_server.log(rt_id_part, 'any tst message to be added to the log')

        out, err = capsys.readouterr()
        assert 'any tst message to be added to the log' not in out
        assert len(threaded_server.reqs_and_logs) == log_len + 1
        req = threaded_server.reqs_and_logs[-1]
        assert req['method_name'] == rt_id_part + "_log"
        assert req['message'] == 'any tst message to be added to the log'
        assert req['completed'] is True
        assert req['log_time']
        assert rt_id_part in req['rt_id']

    def test_log_append_print(self, capsys, threaded_server):
        rt_id_part = 'print'
        assert threaded_server.debug == bool(threaded_server.reqs_and_logs)
        log_len = len(threaded_server.reqs_and_logs)

        threaded_server.log(rt_id_part, 'any tst message to be added to the log')

        out, err = capsys.readouterr()
        assert 'any tst message to be added to the log' in out
        assert len(threaded_server.reqs_and_logs) == log_len + 1
        req = threaded_server.reqs_and_logs[-1]
        assert req['method_name'] == rt_id_part + "_log"
        assert req['message'] == 'any tst message to be added to the log'
        assert req['completed'] is True
        assert req['log_time']
        assert rt_id_part in req['rt_id']

    def test_log_append_verbose(self, capsys, threaded_server):
        rt_id_part = 'verbose'
        threaded_server.debug_level = DEBUG_LEVEL_ENABLED
        assert threaded_server.debug
        assert not threaded_server.verbose
        assert bool(threaded_server.reqs_and_logs)
        log_len = len(threaded_server.reqs_and_logs)

        threaded_server.log(rt_id_part, 'any tst message to be added to the log')

        out, err = capsys.readouterr()
        assert 'any tst message to be added to the log' not in out
        assert len(threaded_server.reqs_and_logs) == log_len

        threaded_server.debug_level = DEBUG_LEVEL_VERBOSE

        threaded_server.log(rt_id_part, 'any tst message to be added to the log')

        out, err = capsys.readouterr()
        assert 'any tst message to be added to the log' in out
        assert len(threaded_server.reqs_and_logs) == log_len + 1
        req = threaded_server.reqs_and_logs[-1]
        assert req['method_name'] == rt_id_part + "_log"
        assert req['message'] == 'any tst message to be added to the log'
        assert req['completed'] is True
        assert req['log_time']
        assert rt_id_part in req['rt_id']

    def test_pending_requests(self, threaded_server):
        rt_id = "rt_id"
        rt_req = {'rt_id': rt_id}
        threaded_server.reqs_and_logs.append(rt_req)
        req = {}
        res = threaded_server.pending_requests(req, MagicMock())
        assert 'error' not in res
        assert threaded_server.reqs_and_logs[0]['rt_id'] == rt_id
        assert threaded_server.reqs_and_logs[0] is rt_req
        assert req['pending_requests'][-1] == rt_req

    def test_pending_requests_with_completed_removed(self, threaded_server):
        rt_id = "rt_id"
        rt_req = {'rt_id': rt_id, 'completed': True}
        threaded_server.reqs_and_logs.append(rt_req)
        req = {}
        res = threaded_server.pending_requests(req, MagicMock())
        assert 'error' not in res
        assert not threaded_server.reqs_and_logs
        assert res['pending_requests'][-1] == rt_req

    def test_pending_requests_with_error_removed(self, threaded_server):
        rt_id = "rt_id"
        rt_req = {'rt_id': rt_id, 'error': "error"}
        threaded_server.reqs_and_logs.append(rt_req)
        req = {}
        res = threaded_server.pending_requests(req, MagicMock())
        assert 'error' not in res
        assert not threaded_server.reqs_and_logs
        assert res['pending_requests'][-1] == rt_req

    def test_recv_file(self, threaded_server, tmp_path):
        PATH_PLACEHOLDERS['downloads'] = str(tmp_path)
        tst_fil = os_path_join(str(tmp_path), 'recv_file_tst.file')
        write_file(tst_fil, "any file content")
        with open(tst_fil, 'rb') as fp:
            req = {'file_path': 'recv_file_tst.file', 'total_bytes': os.fstat(fp.fileno()).st_size}
            handler = MagicMock()
            handler.rfile = fp
            res = threaded_server.recv_file(req, handler)
        assert 'error' in res   # already transferred
        assert threaded_server.reqs_and_logs

    def test_recv_file_aborted_via_progress_callback(self, threaded_server):
        """ simulate cancel_request() injecting 'error' into request_kwargs while copy_bytes() is running,
        so the recv_file()._progress() callback detects it and aborts the transfer. """
        threaded_server.log = MagicMock()
        threaded_server.vpo = MagicMock()
        threaded_server.get_option = MagicMock(return_value=1024)          # buf_len
        request_kwargs: TransferKwargs = {
            'file_path': 'downloads/incoming.bin',
            'total_bytes': 100,
        }
        handler = MagicMock()
        handler.client_address = ('192.168.1.20', 54321)

        progress_results = []

        def fake_copy_bytes(_rfile, _dst, **kwargs):
            errors = kwargs['errors']
            progress_func = kwargs['progress_func']

            # 1st progress tick: transfer still clean -> _progress() updates and returns "" (no abort)
            progress_results.append(progress_func(transferred_bytes=10))

            # another thread/request (e.g. cancel_request()) cancels the transfer in the meantime
            request_kwargs['error'] = "cancelled by peer"

            # 2nd progress tick: _progress() now finds 'error' in request_kwargs and aborts
            result = progress_func(transferred_bytes=20)
            progress_results.append(result)
            assert result  # non-empty string signals copy_bytes to stop
            errors.append(result)

        with (patch('ae.transfer_service.normalize', side_effect=lambda path, **_kw: path),
              patch('ae.transfer_service.os.path.split', return_value=("downloads", "incoming.bin")),
              patch('ae.transfer_service.os.path.exists', return_value=True),
              patch('ae.transfer_service.norm_path', side_effect=lambda path: path),
              patch('ae.transfer_service.os_path_join', side_effect=lambda *parts: "/".join(parts)),
              patch('ae.transfer_service.os_path_isdir', return_value=False),
              patch('ae.transfer_service.os_path_isfile', return_value=False),
              patch('ae.transfer_service.copy_bytes', side_effect=fake_copy_bytes)):
            response_kwargs = threaded_server.recv_file(request_kwargs, handler)

        # 1st tick succeeded (no abort signal)
        assert progress_results[0] == ""
        # 2nd tick hit the early-return branch (line 515) because 'error' was already set
        assert "error in request kwargs" in progress_results[1]
        assert "cancelled by peer" in progress_results[1]  # embedded via the dict repr of request_kwargs

        # the aborted transfer's error propagated into the final response
        assert 'error' in response_kwargs
        assert "error in request kwargs" in response_kwargs['error']

    def test_recv_file_folder_no_file(self, threaded_server, tmp_path):
        req = {'file_path': str(tmp_path), 'total_bytes': 333}
        res = threaded_server.recv_file(req, MagicMock())
        assert 'error' in res
        assert threaded_server.debug == bool(threaded_server.reqs_and_logs)

    def test_recv_file_not_found(self, threaded_server):
        req = {'file_path': "not_exists.tst", 'total_bytes': 333}
        res = threaded_server.recv_file(req, MagicMock())
        assert 'error' in res
        assert threaded_server.debug == bool(threaded_server.reqs_and_logs)

    def test_recv_file_series(self, threaded_server, tmp_path):
        PATH_PLACEHOLDERS['downloads'] = str(tmp_path)
        file_name = os_path_join(str(tmp_path), 'recv_file_series.tst')
        write_file(file_name, "any file content")
        with open(file_name, 'rb') as fp:
            req = {'file_path': 'recv_file_series.tst', 'total_bytes': os.fstat(fp.fileno()).st_size,
                   'series_file': True}
            handler = MagicMock()
            handler.rfile = fp
            res = threaded_server.recv_file(req, handler)
        assert 'error' not in res
        assert threaded_server.debug == bool(threaded_server.reqs_and_logs)
        assert os_path_isfile(res['series_file_name'])
        assert read_file_text(file_name) == read_file_text(res['series_file_name'])

    def test_recv_file_zero_len(self, threaded_server):
        req = {'file_path': "not_exists.xxx", 'total_bytes': 0}
        res = threaded_server.recv_file(req, MagicMock())
        assert 'error' in res
        assert threaded_server.debug == bool(threaded_server.reqs_and_logs)

    def test_recv_message(self, threaded_server):
        msg = "message"
        req = {'message': msg}
        res = threaded_server.recv_message(req, MagicMock())
        assert 'transferred_bytes' in res
        assert res['transferred_bytes'] == len(msg)
        assert 'error' not in res

    def test_response_to_request_err_empty_res(self, threaded_server):
        req = {'method_name': 'patched_meth'}
        setattr(threaded_server, 'patched_meth', lambda *_args, **_kwargs: {})
        res_lit = threaded_server.response_to_request(transfer_kwargs_literal(req), MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' in res

    def test_response_to_request_err_in_req(self, threaded_server):
        req = {'method_name': 'patched_meth', 'error': "req_error"}
        setattr(threaded_server, 'patched_meth', lambda *_args, **_kwargs: {'something': "xxx"})
        res_lit = threaded_server.response_to_request(transfer_kwargs_literal(req), MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' in res
        assert threaded_server.reqs_and_logs[-1]['method_name'] == 'patched_meth'
        assert threaded_server.reqs_and_logs[-1]['error'] == "req_error"

    def test_response_to_request_err_in_res(self, threaded_server):
        req = {'method_name': 'patched_meth'}
        setattr(threaded_server, 'patched_meth', lambda *_args, **_kwargs: {'error': "res_error"})
        res_lit = threaded_server.response_to_request(transfer_kwargs_literal(req), MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' in res
        assert threaded_server.reqs_and_logs[-1]['method_name'] == 'patched_meth'
        assert threaded_server.reqs_and_logs[-1]['error'] == "res_error"
        assert res['error'] == "res_error"

    def test_response_to_request_err_invalid_lit(self, threaded_server):
        res_lit = threaded_server.response_to_request("{xxx", MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' in res

    def test_response_to_request_pending_requests(self, threaded_server):
        req = {'method_name': 'pending_requests'}
        res_lit = threaded_server.response_to_request(transfer_kwargs_literal(req), MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' not in res

    def test_response_to_request_recv_message(self, threaded_server):
        msg = "message"
        req = {'method_name': 'recv_message', 'message': msg}
        res_lit = threaded_server.response_to_request(transfer_kwargs_literal(req), MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' not in res

    def test_response_to_request_recv_message_completed(self, threaded_server):
        msg = "message"
        req = {'method_name': 'recv_message', 'message': msg, 'total_bytes': len(msg)}
        res_lit = threaded_server.response_to_request(transfer_kwargs_literal(req), MagicMock())
        res = transfer_kwargs_from_literal(res_lit)
        assert 'error' not in res

    def test_send_file(self, threaded_server, tmp_path):
        PATH_PLACEHOLDERS['downloads'] = str(tmp_path)
        file_content = "send file test content"
        file_len = len(file_content)
        file_path = os_path_join(str(tmp_path), 'send_file.test')
        write_file_text(file_content, file_path)
        req = {'file_path': file_path, 'local_ip': os_local_ip(), 'remote_ip': os_local_ip(), 'total_bytes': file_len}
        res = threaded_server.send_file(req, MagicMock())
        assert 'transferred_bytes' in res
        assert res['transferred_bytes'] == file_len
        assert res['file_path'] == os_path_join('{downloads}', 'send_file.test')  # != file_path
        assert 'error' not in res

    def test_send_file_already_transferred(self, threaded_server, tmp_path):
        PATH_PLACEHOLDERS['downloads'] = str(tmp_path)
        file_path = os_path_join(str(tmp_path), 'already_sent_test.test')
        write_file(file_path, "content of\nan already transferred file\n\n\n")
        with open(file_path, 'rb') as fp:
            file_len = os.fstat(fp.fileno()).st_size
        req = {'file_path': file_path, 'local_ip': os_local_ip(), 'remote_ip': 'localhost', 'total_bytes': file_len}
        res = threaded_server.send_file(req, MagicMock())
        assert 'transferred_bytes' in res
        assert res['transferred_bytes']
        assert res['file_path'] == os_path_join('{downloads}', 'already_sent_test.test')  # file_path
        assert 'error' in res

    def test_send_file_empty(self, threaded_server, tmp_path):
        file_path = os_path_join(str(tmp_path), 'test_send_file.zzz')
        write_file_text("", file_path)
        req = {'file_path': file_path, 'local_ip': os_local_ip(), 'remote_ip': 'localhost', 'total_bytes': 0}
        res = threaded_server.send_file(req, MagicMock())
        assert 'transferred_bytes' in res
        assert not res['transferred_bytes']
        assert 'error' in res
        assert os_path_isfile(file_path)

    def test_send_file_not_existing(self, threaded_server):
        file_path = "zzz.y"
        req = {'file_path': file_path, 'local_ip': os_local_ip(), 'remote_ip': 'localhost', 'total_bytes': 111}
        res = threaded_server.send_file(req, MagicMock())
        assert 'transferred_bytes' not in res
        assert 'error' in res

    def test_send_file_recovers_interrupted_transfer(self, threaded_server):
        threaded_server.log = MagicMock()
        threaded_server.vpo = MagicMock()
        threaded_server.get_option = MagicMock(return_value=1024)  # buf_len
        file_content = b"0123456789" * 10  # 100 bytes total
        offset = 40  # bytes already received by the remote peer

        request_kwargs: TransferKwargs = {
            'file_path': '/local/path/file.bin',
            'local_ip': '192.168.1.10',
            'remote_ip': '192.168.1.20',
        }
        handler = MagicMock()
        handler.client_address = ('192.168.1.20', 54321)

        recv_file_response = {'transferred_bytes': offset}  # no 'error' key -> no early return

        sock_cm = MagicMock()
        sock_instance = MagicMock(spec=socket)
        sock_cm.__enter__.return_value = sock_instance

        with patch('ae.transfer_service.open', mock_open(read_data=file_content)), \
                patch('ae.transfer_service.placeholder_path', side_effect=lambda path: path), \
                patch('ae.transfer_service.socket.socket', return_value=sock_cm), \
                patch('ae.transfer_service.connect_and_request', return_value=recv_file_response) as conn_mock:
            response_kwargs = threaded_server.send_file(request_kwargs, handler)

        # verify the initial recv_file request was addressed to the remote peer, not re-sent with a stale offset
        sent_recv_kwargs = conn_mock.call_args.args[1]
        assert sent_recv_kwargs['method_name'] == 'recv_file'
        assert sent_recv_kwargs['server_address'] == ('192.168.1.20', SERVER_PORT)
        assert sent_recv_kwargs['transferred_bytes'] == 0  # initial guess before the peer reports its offset

        # only the remaining bytes (after offset) got sent in a single chunk (buf_len=1024 > remaining 60 bytes)
        sock_instance.send.assert_called_once_with(file_content[offset:])

        # both dicts reflect the completed transfer afterward
        assert request_kwargs['transferred_bytes'] == len(file_content)
        assert response_kwargs['transferred_bytes'] == len(file_content)
        assert 'error' not in response_kwargs

        # the "recovering interrupted transfer" debug message was logged with the correct offset
        debug_messages = [c.args[1] for c in threaded_server.log.call_args_list if c.args[0] == 'debug']
        assert any(f"recovering interrupted transfer at offset {offset}" in msg for msg in debug_messages)

    def test_send_message(self, threaded_server):
        msg = "message"
        req = {'message': msg, 'local_ip': os_local_ip(), 'remote_ip': 'localhost'}  # os_local_ip())
        res = threaded_server.send_message(req, MagicMock())
        assert 'transferred_bytes' in res
        assert res['transferred_bytes'] == len(msg)
        assert res['message'] == msg
        assert 'error' not in res

    def test_shutdown(self, threaded_server):
        with patch('ae.console.ConsoleApp.shutdown') as mock_shutdown:
            threaded_server.shutdown()

        mock_shutdown.assert_called_once()

    def test_start_server(self, restore_app_env):
        app = service_factory()
        thread = threading.Thread(target=app.start_server)
        thread.start()
        retries = 69
        while retries > 0 and (not app.server_instance or not app.server_thread):
            time.sleep(.1)
            retries -= 1
        app.stop_server()
        assert retries > 0

    def test_start_server_exception(self, restore_app_env):
        invalid_addr = ":invalid bind address:"
        invalid_port = ":invalid port:"
        app = service_factory()
        app.run_app()
        app.set_option('bind', invalid_addr, save_to_config=False)
        app.set_option('port', invalid_port, save_to_config=False)
        requests_lock.acquire()

        err = app.start_server(threaded=True)

        assert invalid_addr in err or invalid_port in err
        app.stop_server()

    def test_stop_server_release_lock(self, capsys, threaded_server):
        requests_lock.acquire()

        threaded_server.stop_server()

        assert threaded_server.server_instance is None
        assert threaded_server.server_thread is None
        out, err = capsys.readouterr()
        assert "released requests lock" in out

    def test_stop_server_stop_thread(self, capsys, threaded_server):
        mock_thread = MagicMock(spec=threading.Thread)
        # noinspection PyUnresolvedReferences
        threaded_server.server_instance.shutdown()  # stop threaded_server test thread before stop thread unit test

        with (patch('ae.transfer_service.threading.current_thread', return_value=threaded_server.server_thread),
              patch('ae.transfer_service.threading.Thread', return_value=mock_thread)):
            threaded_server.stop_server()

        mock_thread.start.assert_called_once()
        mock_thread.join.assert_called_once()
        mock_thread.is_alive.assert_called_once()
        assert threaded_server.server_instance is None
        assert threaded_server.server_thread is None
        out, err = capsys.readouterr()
        assert "server shutdown thread join timed out" in out

    def test_stop_server_timed_out(self, capsys, threaded_server):
        with patch.object(threaded_server.server_thread, 'is_alive'):
            threaded_server.stop_server()

        assert threaded_server.server_instance is None
        assert threaded_server.server_thread is None
        out, err = capsys.readouterr()
        assert "server thread join timed out" in out
