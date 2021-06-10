"""
transfer client and server services
===================================

This ae portion is providing client and server services for to transfer files and text messages between two devices in
the same local network.

The number of parallel running file and message transfers is only limited by the available resources of the involved
devices.

If a file transfers gets interrupted it can be recovered later and without the need to resend the already transferred
file content.

Standard file paths - like e.g. the Documents or Downloads folders - are getting automatically adopted to the specific
path structures of each involved device and operating system.


transfer service life cycle
---------------------------

The transfer service can be invoked in different ways: standalone as a separate process or attached and embedded into
a controlling application.


run transfer service in standalone mode
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Execute this module for to run the transfer services as a separate standalone process via::

    python transfer_service.py [--bind=...] [--port=...] [--buf_len=...]

The following command line options are overwriting the default server address and socket buffer length (see also
:func:`service_factory`):

* 'bind' to restrict the incoming connections to an ip address/range (overwriting the default :data:`SERVER_BIND`).
* 'port' to specify the socket port (overwriting the default port :data:`SERVER_PORT`).
* 'buf_len' to specify the socket buffer length (overwriting the default buffer length :data:`SOCKET_BUF_LEN`).

After that the transfer service will be able to receive files send from another process or device.

.. note::
    On Android a standalone transfer service has to be started as android service.


run transfer service attached to any app
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Alternatively you can run the transfer service server in a separate thread within respectively attached to your
application::

    from ae.transfer_service import service_factory

    transfer_service_app = service_factory()
    transfer_service_app.set_option('port', 12345, save_to_config=False)
    transfer_service_app.set_option('buf_len', 34567, save_to_config=False)
    transfer_service_app.start_server(threaded=True)


pause or stop transfer service
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For to manually pause the transfer service, store the app instance of the transfer service app
(`transfer_service_app` in the example above) and call its :meth:`~TransferServiceApp.stop_server` method::

    transfer_service_app.stop_server()

For to fully stop the transfer service and terminate the transfer service app call instead its
:meth:`~TransferServiceApp.shutdown` method::

    transfer_service_app.shutdown()

.. hint::
    The :meth:`~ae.core.AppBase.shutdown` method of the base app instance (:class:`~ae.core.AppBase`) automatically
    ensures a clean shutdown of the transfer service server on app quit/exit.


send file to another transfer service server
--------------------------------------------

For to send files from one transfer server to another running transfer server, a separate client process has to be
started on the device storing the file to be send.

For to initiate the file transfer the client process has to make a tcp connection to the transfer server running on the
same device, specifying the path of the file to send and the remote ip of the receiving transfer server and finally call
the remote procedure `send_file` like shown in the following example::

    import socket
    from ae.transfer_service import connect_and_request

    request_kwargs = dict(method_name='send_file', file_path='path_to_file/file_name.ext', remote_ip='192.168.3.123')
    with socket.socket() as sock:
        response_kwargs = connect_and_request(sock, request_kwargs)

    if 'error' in response_kwargs:
        # handle error (e.g. display to user or add to a log file)

If the file transfer failed then the transfer kwargs dict returned by :func:`connect_and_request` will contain an
`error` key containing the error message text.


implemented remote procedures
-----------------------------

The following remote procedures are provided by the transfer service server:

* `cancel_request`: cancel running file transfer.
* `pending_requests`: get log info the progress/status of all currently running file transfers.
* `recv_file`: receive file from other transfer service server.
* `recv_message`: receive text message from other transfer service server.
* `send_file`: send file to other transfer service server.
* `send_message`: send text message to other transfer service server.

.. hint::
    The demo app `ComPartY <https://gitlab.com/ae-group/comparty>`_ is using all provided remote procedures.

"""
import ast
import datetime
import os
import socket
import threading

from copy import deepcopy
from socketserver import StreamRequestHandler, ThreadingTCPServer
from typing import Any, Callable, Dict, List, Optional, Union

from ae.base import DATE_TIME_ISO, UNSET, os_local_ip                                                   # type: ignore
from ae.files import copy_bytes                                                                         # type: ignore
from ae.paths import PATH_PLACEHOLDERS, norm_path, placeholder_path, series_file_name                   # type: ignore
from ae.deep import deep_replace                                                                        # type: ignore
from ae.console import ConsoleApp                                                                       # type: ignore


__version__ = '0.2.8'


CONNECTION_TIMEOUT = 2.7            #: default timeout (in seconds) for to connect and request a server process

CONNECT_ERR_PREFIX = "transfer_service.connect_and_request() exception "
""" error message string prefix if error happened directly in :func:`connect_and_request` helper (no protocol error).
"""

ENCODING_KWARGS = dict(encoding='UTF-8', errors='ignore')   #: default encoding and encoding error handling strategy

SERVER_BIND = ""                    #: setting BIND to '' or None for to allow connections for all available interfaces
SERVER_PORT = 36969                 #: server listening port

SHUTDOWN_TIMEOUT = 3.9              #: timeout (in seconds) to shutdown/stop the console app

SOCKET_BUF_LEN = 16 * 1024          #: buf length for socket receives and sends

TRANSFER_KWARGS_DATE_TIME_NAME_PARTS = ('_date', '_time')   #: kwarg name suffix for values automatically converted
TRANSFER_KWARGS_LINE_END_CHAR = "\n"                        #: end of line/command character as string
TRANSFER_KWARGS_LINE_END_BYTE = bytes(TRANSFER_KWARGS_LINE_END_CHAR, **ENCODING_KWARGS)     #: .. and as byte value

# InetAddress = Tuple[str, int]     #: for socket.connect / server.bind
TransferKwargs = Dict[str, Any]     #: command/action format of requests and responses


requests_lock = threading.Lock()    #: locking requests TransferKwargs in :attr:`TransferServiceApp.reqs_and_logs`

server_app: Optional['TransferServiceApp'] = None     #: transfer service server app


def clean_log_str(log_str: Union[str, bytes]) -> str:
    """ remove high-commas and backslashes from the passed string for to add it to the logs (preventing \\ duplicates).

    :param log_str:             log string or bytes array to clean up.
    :return:                    cleaned log string.
    """
    if isinstance(log_str, bytes):
        log_str = str(log_str, **ENCODING_KWARGS)
    log_str = log_str.replace("\\n", "")
    log_str = log_str.replace("\n", "")
    log_str = log_str.replace("\r", "")
    log_str = log_str.replace("\\", "")
    log_str = log_str.replace("'", "")
    return log_str.replace('"', "")


def connect_and_request(sock: socket.socket, request_kwargs: TransferKwargs,
                        buf_len: int = SOCKET_BUF_LEN, timeout: Optional[float] = CONNECTION_TIMEOUT) -> TransferKwargs:
    """ connect to remote, send first command/action and return response as transfer kwargs dict.

    :param sock:                new socket instance.
    :param request_kwargs:      first/initial request kwargs dict. If the key `'server_address'` is not provided (with
                                the server address as (host, ip) tuple), then ('localhost', SERVER_PORT) is used.
                                If the key 'local_ip' is not specified then the local ip address will be used.
    :param buf_len:             socket buffer length. If not passed then :data:`SOCKET_BUF_LEN` will be used. Pass
                                zero/0 for to use the buf length defined via the 'buf_len' command line option.
    :param timeout:             timeout in seconds or None for to use socket/system default timeout. If not passed
                                then the default timeout specified by :data:`CONNECTION_TIMEOUT` will be used.
    :return:                    response transfer kwargs dict.
    """
    if 'local_ip' not in request_kwargs:
        request_kwargs['local_ip'] = os_local_ip()
    server_app and server_app.vpo(f"transfer_service.connect_and_request(): timeout={timeout} req={request_kwargs}")

    try:
        sock.settimeout(timeout)
        sock.connect(request_kwargs.get('server_address', ('localhost', SERVER_PORT)))
        sock.sendall(bytes(transfer_kwargs_literal(request_kwargs), **ENCODING_KWARGS))
        response_lit = str(recv_bytes(sock, buf_len=buf_len), **ENCODING_KWARGS)[:-1]
        return transfer_kwargs_from_literal(response_lit)
    except (Exception, IOError, OSError, SyntaxError, ValueError) as ex:
        request_kwargs['error'] = CONNECT_ERR_PREFIX + f"{ex} processing received request {request_kwargs}"
        return request_kwargs


def recv_bytes(sock: socket.socket, buf_len: int = SOCKET_BUF_LEN) -> bytes:
    """ receive all bytes from the passed client socket instance until connection lost or line end reached.

    :param sock:                socket instance.
    :param buf_len:             socket buffer length. If not passed then :data:`SOCKET_BUF_LEN` will be used. Pass
                                zero/0 for to use the buf length defined via the 'buf_len' command line option.
    :return:                    received bytes.
    """
    pre = "transfer_service.recv_bytes()"
    if not buf_len:
        buf_len = server_app.get_opt('buf_len') if server_app else SOCKET_BUF_LEN
    server_app and server_app.vpo(f"{pre}: sock={sock} buf_len={buf_len} ... waiting for receive")
    buf = b""
    while True:
        chunk = sock.recv(buf_len)
        server_app and server_app.vpo(f"{pre}: received {len(chunk)} bytes chunk=({clean_log_str(chunk)}); sock={sock}")
        buf += chunk
        if buf[-1:] == TRANSFER_KWARGS_LINE_END_BYTE:
            server_app and server_app.vpo(f"{pre}: received end-of-line-char from socket {sock}")
            break
        if not chunk:   # pragma: no cover
            server_app and server_app.vpo(f"{pre}: received empty chunk from socket {sock}")
            buf = bytes(transfer_kwargs_literal(dict(error=f"{pre}: empty chunk error")), **ENCODING_KWARGS)
            break
    return buf


def service_factory(task_id_func: Optional[Callable[[str, str, str], str]] = None) -> 'TransferServiceApp':
    """ create server app instance including the command line options `bind` and `port`.

    :param task_id_func:        callable for to return an unique id for a transfer request task.
    :return:                    transfer service app instance.
    """
    global server_app           #: singleton server instance

    server_app = TransferServiceApp(app_name='transfer_service', multi_threading=True, disable_buffering=True)
    server_app.add_option('bind', "server bind address", SERVER_BIND, 'b')
    server_app.add_option('port', "server listening port", SERVER_PORT, 'p')
    server_app.add_option('buf_len', "socket buffer length", SOCKET_BUF_LEN, 'l')

    if task_id_func:
        # noinspection PyTypeHints
        server_app.id_of_task = task_id_func    # type: ignore

    return server_app


def transfer_kwargs_error(transfer_kwargs: TransferKwargs, err_msg: str):
    """ add/append error to transfer kwargs dict without overwriting any previous error.
    :param transfer_kwargs:     request/response transfer kwargs dict.
    :param err_msg:             error message to add.
    """
    old_err = transfer_kwargs.get('error', "")
    if old_err:
        err_msg = f"{old_err}+++{err_msg}"
    transfer_kwargs['error'] = err_msg


def transfer_kwargs_from_literal(transfer_kwargs_lit: str) -> TransferKwargs:
    """ convert dict literal (created with transfer_kwargs_literal()) to transfer kwargs dict.

    :param transfer_kwargs_lit: request/response dict literal string.
    :return:                    transfer kwargs dict.
    """
    transfer_kwargs = ast.literal_eval(transfer_kwargs_lit)
    deep_replace(
        transfer_kwargs,
        lambda dp, key, val:
            datetime.datetime(*val)
            if isinstance(key, str) and any(fragment in key for fragment in TRANSFER_KWARGS_DATE_TIME_NAME_PARTS)
            else UNSET)
    return transfer_kwargs


def transfer_kwargs_literal(transfer_kwargs: TransferKwargs) -> str:
    """ convert dict to str literal for to be sent via sockets (re-instantiable via transfer_kwargs_from_literal()).

    .. note::
        For to ensure security (and prevent injections) only the following basic types can be used: `int`, `float`,
        `boolean`, `str`, `bytes`, `list`, `tuple` and `dict`. Date/Time values are only allowed as dict value and of
        the type `datetime.datetime`; additionally the key of this dict value has to contain one of the fragments
        defined in :data:`TRANSFER_KWARGS_DATE_TIME_NAME_PARTS`.

    :param transfer_kwargs:     request/response transfer kwargs dict.
    :return:                    literal string of transfer kwargs dict terminated with TRANSFER_KWARGS_LINE_END_CHAR.
    """
    transfer_kwargs = deepcopy(transfer_kwargs)
    deep_replace(
        transfer_kwargs,
        lambda pd, key, val:
            tuple(val.timetuple())[:7]
            if isinstance(key, str) and any(fragment in key for fragment in TRANSFER_KWARGS_DATE_TIME_NAME_PARTS)
            else UNSET)
    ret = str(transfer_kwargs).replace(TRANSFER_KWARGS_LINE_END_CHAR, "\\n") + TRANSFER_KWARGS_LINE_END_CHAR
    return ret


def transfer_kwargs_update(*variables, **kwargs):
    """ update multiple transfer dicts with the same keys/values (locking with requests_lock).

    :param variables:           transfer kwargs variables/dicts.
    :param kwargs:              kwargs to update.
    """
    requests_lock.acquire()
    for var in variables:
        var.update(**kwargs)
    requests_lock.release()


class ThreadedTCPRequestHandler(StreamRequestHandler):
    """ server request handler.

    self.rfile is a file-like object created by the handler; for to use e.g. readline() instead of raw recv()
    Likewise, self.wfile is a file-like object used to write back to the client.
    """
    def handle(self):
        """ handle a single request """
        pre = "ThreadedTCPRequestHandler.handle() "
        try:
            request_lit = str(self.rfile.readline(), **ENCODING_KWARGS)[:-1]
            server_app.vpo(f"{pre}request len={len(request_lit)}; req={clean_log_str(request_lit)}")
            response_lit = server_app.response_to_request(request_lit, self)
            server_app.vpo(f"{pre}response len={len(response_lit)}; res={clean_log_str(response_lit)}")
            self.wfile.write(bytes(response_lit, **ENCODING_KWARGS))
        except (IOError, OSError, Exception) as ex:
            server_app.log('print', f"{pre}error: {ex}")


class TransferServiceApp(ConsoleApp):
    """ server service app class """
    reqs_and_logs: List[TransferKwargs]                 #: list of transfer_kwargs of currently processed requests
    server_instance: Optional[ThreadingTCPServer]       #: server class instance
    server_thread: Optional[threading.Thread]           #: server thread (main or separate thread)

    def cancel_request(self, request_kwargs: TransferKwargs, handler: StreamRequestHandler) -> TransferKwargs:
        """ cancel running request.

        :param request_kwargs:  request transfer kwargs dict, specifying via `rt_id_to_cancel` the request to cancel.
        :param handler:         request handler instance.
        :return:                response kwargs, having `error` key if request could not be found/cancelled.
        """
        pre = "TransferServiceApp.cancel_request()"
        rt_id_to_cancel = request_kwargs['rt_id_to_cancel']
        msg = f"'{rt_id_to_cancel}' from client {handler.client_address}"
        self.log('debug', f"{pre}: {msg}")

        response_kwargs = request_kwargs.copy()
        requests_lock.acquire()
        for req in self.reqs_and_logs:
            if req['rt_id'] == rt_id_to_cancel:
                req['error'] = msg + " cancelled"
                request_kwargs['completed'] = True
                break
        else:
            response_kwargs['error'] = msg + " not found/cancelled"
        requests_lock.release()

        return response_kwargs

    @staticmethod
    def id_of_task(action: str, object_type: str, object_key: str) -> str:
        """ compile the id of a transfer request task.

        :param action:          action or log level string.
        :param object_type:     task object type ('log' for log entries, 'file' for file transfers, else 'message').
        :param object_key:      task key (file path for file transfers, message string for messages and timestamp
                                for log entries).
        :return:                unique key identifying the task/log-entry.
        """
        return action + '_' + object_type + ':' + object_key

    def log(self, log_level: str, message: str):
        """ print log message and add it to reqs_and_logs (for to be read by controller app).

        .. note::
            Please note that you have to use :func:`print` or one of the console print methods of the :class:`AppBase`
            (like e.g. :meth:`~AppBase.verbose_out`, respective self.vpo) instead of this method for the logging of
            low level transport methods/functions (like e.g. :meth:`~TransferServiceApp.pending_requests`,
            :meth:`~TransferServiceApp.response_to_request`, :meth:`~ThreadedTCPRequestHandler.handle` or
            :func:`recv_bytes`). This will prevent the duplication of a log message, because each call of this method
            creates a new entry in :attr:`~TransferServiceApp.reqs_and_logs` which will be sent to the controlling app
            via the low level transport methods (which would recursively grow the sent messages until the system
            freezes), especially if the transfer kwargs are included into the log message.

        :param log_level:       'print' always prints, 'debug' prints if self.debug, 'verbose' prints if self.verbose.
        :param message:         message to print.
        """
        out_method = getattr(self, log_level + '_out', None)    # calling print() via self.po/.dpo/.vpo()
        if callable(out_method):
            out_method(("" if self.active_log_stream else f"{threading.current_thread().name: <15}") + f"{message}")

        if getattr(self, log_level, True) and hasattr(self, 'reqs_and_logs'):
            log_time = datetime.datetime.now()

            requests_lock.acquire()
            self.reqs_and_logs.append(dict(
                method_name=log_level + '_' + 'log', message=message, completed=True,
                log_time=log_time, rt_id=self.id_of_task(log_level, 'log', log_time.strftime(DATE_TIME_ISO))))
            requests_lock.release()

    def pending_requests(self, request_kwargs: TransferKwargs, handler: StreamRequestHandler) -> TransferKwargs:
        """ determine currently running/pending server requests and debug log messages (in debug mode only).

        :param request_kwargs:  request transfer kwargs dict.
        :param handler:         request handler class instance.
        :return:                response transfer kwargs dict keys.
        """
        self.vpo(f"TransferServiceApp.pending_requests {request_kwargs} from {handler.client_address}")

        requests_lock.acquire()

        # copy all log messages and pending transfer requests (the pending_requests get not added to reqs_and_logs)
        request_kwargs['pending_requests'] = self.reqs_and_logs.copy()

        # remove completed transfers, cancellations, errors and debug log messages (just passed to the controlling app)
        self.reqs_and_logs[:] = [_ for _ in self.reqs_and_logs if 'completed' not in _ and 'error' not in _]

        requests_lock.release()

        return request_kwargs

    # uncomment the following method for verbose logging/debugging of threading issues
    # def po(self, *objects, **kwargs):
    #     """ overwritten to add thread name to console printouts. """
    #     if not self.active_log_stream:
    #         objects = (f"{threading.current_thread().name: <18}", ) + objects
    #     super().po(*objects, **kwargs)

    def recv_file(self, request_kwargs: TransferKwargs, handler: StreamRequestHandler) -> TransferKwargs:
        """ receive binary file content from client.

        :param request_kwargs:  request transfer kwargs dict with the following keys:

                                * `'file_path'`: file path (can contain path placeholders).
                                * `'total_bytes'`: total file length in bytes.
                                * `'series_file'`: optionally, pass any value for to ensures new file name.

        :param handler:         request handler class instance.

        :return:                response transfer kwargs dict keys (request kwargs extended with additional keys):

                                * `'error'`: error message string if an error occurred.
                                * `'transferred_bytes'`: start offset on recovered transfer (previously received bytes).
        """
        file_path = norm_path(request_kwargs['file_path'])
        file_folder, file_name = os.path.split(file_path)
        if not os.path.exists(file_folder):
            file_folder = PATH_PLACEHOLDERS['downloads']
        recv_file = os.path.join(file_folder, file_name)
        if request_kwargs.get('series_file'):
            recv_file = request_kwargs['series_file_name'] = series_file_name(recv_file)
        file_length = request_kwargs['total_bytes']

        pre = "TransferServiceApp.recv_file()"
        self.log('debug', f"{pre}: receive '{recv_file}' ({file_length} bytes) from client {handler.client_address}")

        if not recv_file or not file_length:
            request_kwargs['error'] = f"{pre} called without file name/length arguments"
            return request_kwargs
        if not os.path.exists(recv_file):
            start_offset = 0
        elif not os.path.isfile(recv_file):
            request_kwargs['error'] = f"{pre} destination {recv_file} is not a file"
            return request_kwargs
        else:
            with open(recv_file, 'ab+') as file_handle:
                file_handle.seek(0, 2)
                start_offset = file_handle.tell()  # ==os.fstat(...).st_size; tell() faster: EOF seek anyway needed
            self.log('debug', f"{pre}: recovering interrupted transfer at position {start_offset}")

        transfer_kwargs_update(request_kwargs, transferred_bytes=start_offset)
        if start_offset >= file_length:
            msg = "already transferred" if start_offset == file_length else f"size err {start_offset}>{file_length}"
            self.log('print', f"{pre}: file {msg}")
            request_kwargs['error'] = f"{pre}: file {msg}"
            return request_kwargs

        response_kwargs = request_kwargs.copy()
        handler.wfile.write(bytes(transfer_kwargs_literal(response_kwargs), **ENCODING_KWARGS))

        def _progress(**kwargs) -> str:
            """ copy_bytes progress callback.
            :param kwargs:      transfer kwargs to update.
            :return:            error message string if error (from other thread) detected, else empty string.
            """
            self.vpo(f"{pre}._progress(): copy bytes progress kwargs={kwargs}")
            if 'error' in request_kwargs:   # pragma: no cover
                return f"{pre}._progress(): error in request kwargs={request_kwargs}"   # cancel transfer
            transfer_kwargs_update(request_kwargs, response_kwargs, **kwargs)
            return ""

        errors: List[str] = list()
        copy_bytes(handler.rfile, recv_file, total_bytes=file_length, transferred_bytes=start_offset,
                   buf_size=self.get_opt('buf_len'), recoverable=True, errors=errors, progress_func=_progress)
        if errors:
            transfer_kwargs_update(request_kwargs, response_kwargs, error="\n".join(errors))

        return response_kwargs

    def recv_message(self, request_kwargs: TransferKwargs, handler: StreamRequestHandler) -> TransferKwargs:
        """ receive message from client/peer. """
        msg = request_kwargs['message']
        self.log('debug', f"TransferServiceApp.recv_message '{msg}' from client {handler.client_address}")
        response_kwargs = request_kwargs.copy()
        response_kwargs['transferred_bytes'] = len(msg)

        return response_kwargs

    def response_to_request(self, request_lit: str, handler: StreamRequestHandler) -> str:
        """ process request to this server and return response string.

        .. note:: this method is running in a separate thread (created by the server for to process this request).

        :param request_lit:     request string, which is a dict literal with `'method_name'` key.
        :param handler:         stream request handler instance.
        :return:                response string with transfer kwargs as literal.
                                if an error occurred then the returned response kwargs contains an `'error'` key
                                which stores the related error message.
        """
        pre = "TransferServiceApp.response_to_request()"
        self.vpo(f"{pre} from client={handler.client_address} request={request_lit}")

        try:
            request_kwargs = transfer_kwargs_from_literal(request_lit)
        except (KeyError, SyntaxError, ValueError) as ex:
            self.po(f"{pre} exception {ex} on eval of request literal {request_lit[:180]}...")
            response_kwargs = dict(error=f"{pre} exception='{ex}' in parsing the request literal '{request_lit}'")
        else:
            response_kwargs = dict()        # default response if exception get raised
            method_name = request_kwargs['method_name']
            try:
                if method_name != 'pending_requests':
                    requests_lock.acquire()
                    self.reqs_and_logs.append(request_kwargs)               # removed in pending_requests()
                    requests_lock.release()

                response_kwargs = getattr(self, method_name)(request_kwargs, handler)
                if not response_kwargs:
                    raise IOError(f"{method_name} call returned empty response={response_kwargs}; req={request_kwargs}")

                if 'error' in response_kwargs:                              # cancelled by other peer
                    transfer_kwargs_error(request_kwargs, response_kwargs['error'])
                elif 'error' in request_kwargs:                             # cancel_request() called by this peer
                    transfer_kwargs_error(response_kwargs, request_kwargs['error'])
                elif 'transferred_bytes' in response_kwargs:                # update pending requests progress
                    transferred = response_kwargs['transferred_bytes']
                    requests_lock.acquire()
                    if transferred and transferred == request_kwargs.get('total_bytes', 0):
                        request_kwargs['transferred_bytes'] = transferred
                        request_kwargs['completed'] = True
                    requests_lock.release()

            except (KeyError, IOError, OSError, SyntaxError, ValueError, Exception) as ex:
                self.log('print', f"{pre} {method_name} exception {ex}; req={request_kwargs}; res={response_kwargs}")
                if not response_kwargs:
                    response_kwargs = request_kwargs.copy()
                transfer_kwargs_error(response_kwargs, f"{pre} exception '{ex}' req={request_kwargs}")

        return transfer_kwargs_literal(response_kwargs)

    def send_file(self, request_kwargs: TransferKwargs, handler: StreamRequestHandler) -> TransferKwargs:
        """ send binary file content to remote server. """
        pre = "TransferServiceApp.send_file()"
        file_path = request_kwargs['file_path']
        try:
            with open(file_path, 'rb') as file_handle:
                content = file_handle.read()
            count = len(content)
        except (FileNotFoundError, IOError, OSError) as ex:
            self.log('print', f"{pre} exception {ex} on reading {file_path} file content; request={request_kwargs}")
            request_kwargs['error'] = f"{pre} exception {ex} while reading content of file {file_path} to be send"
            return request_kwargs

        transfer_kwargs_update(request_kwargs, total_bytes=count, transferred_bytes=0)
        if not count:
            request_kwargs['error'] = f"file {file_path} is empty"
            return request_kwargs

        self.log('debug', f"{pre} {count} bytes on behalf of {handler.client_address}; req={request_kwargs}")

        file_path = placeholder_path(request_kwargs['file_path'])
        local_ip = request_kwargs['local_ip']
        remote_ip = request_kwargs['remote_ip']
        recv_kwargs = dict(method_name='recv_file', file_path=file_path,
                           transferred_bytes=0, total_bytes=request_kwargs['total_bytes'],
                           remote_ip=remote_ip, local_ip=local_ip,
                           server_address=(remote_ip, SERVER_PORT),
                           rt_id=self.id_of_task('recv', 'file', file_path + '@' + local_ip))
        if remote_ip == local_ip:
            recv_kwargs['series_file'] = True   # create duplicate for debugging and testing
        with socket.socket() as sock:           # use socket default args: socket.AF_INET, socket.SOCK_STREAM
            response_kwargs = connect_and_request(sock, recv_kwargs, buf_len=0)
            self.log('verbose', f"{pre} received response to {recv_kwargs['method_name']} method: {response_kwargs}")
            if 'error' in response_kwargs:
                return response_kwargs

            requests_lock.acquire()
            offset = request_kwargs['transferred_bytes'] = response_kwargs['transferred_bytes']
            requests_lock.release()
            if offset:      # pragma: no cover
                self.log('debug', f"{pre} recovering interrupted transfer at offset {offset}")
                content = content[offset:]

            # instead of sock.sendall(content) send in chunks for to allow progress display
            buf_len = self.get_opt('buf_len')
            while offset < count and 'error' not in request_kwargs:
                chunk = content[:buf_len]
                sock.send(chunk)
                offset += len(chunk)
                transfer_kwargs_update(request_kwargs, response_kwargs, transferred_bytes=offset)
                content = content[buf_len:]

        return response_kwargs

    def send_message(self, request_kwargs: TransferKwargs, handler: StreamRequestHandler) -> TransferKwargs:
        """ send message to remote server. """
        pre = "TransferServiceApp.send_message()"
        self.log('debug', f"{pre} {request_kwargs} on behalf of {handler.client_address}")

        requests_lock.acquire()
        msg = request_kwargs['message']
        request_kwargs['total_bytes'] = len(msg)
        request_kwargs['transferred_bytes'] = 0
        requests_lock.release()

        recv_kwargs = request_kwargs.copy()
        recv_kwargs['method_name'] = 'recv_message'
        recv_kwargs['server_address'] = (recv_kwargs['remote_ip'], SERVER_PORT)
        recv_kwargs['rt_id'] = self.id_of_task('recv', 'message', msg + '@' + recv_kwargs['local_ip'])

        with socket.socket() as sock:           # use socket default args: socket.AF_INET, socket.SOCK_STREAM
            response_kwargs = connect_and_request(sock, recv_kwargs, buf_len=0)
        self.log('verbose', f"{pre}: received response to {recv_kwargs['method_name']} method call: {response_kwargs}")

        return response_kwargs

    def shutdown(self, exit_code: Optional[int] = 0, timeout: Optional[float] = None):
        """ overwritten for to stop a running transfer service server/threads on shutdown of this app instance.

        :param exit_code:   set application OS exit code - see :meth:`~ae.core.AppBase.shutdown`.
        :param timeout:     timeout float value in seconds - see :meth:`~ae.core.AppBase.shutdown`.
        """
        self.stop_server()
        super().shutdown(exit_code=exit_code, timeout=timeout)

    def start_server(self, threaded: bool = False) -> str:
        """ start server and run until main app :meth:`~.stop_server`.

        :param threaded:        optionally pass True to use separate thread for the server process.
        :return:                empty string/"" if server instance/thread got started else error message string.
        """
        pre = "TransferServiceApp.start_server()"
        self.reqs_and_logs = list()
        self.server_instance = self.server_thread = None

        if requests_lock.locked():      # pragma: no cover
            requests_lock.release()     # reset from crashed request
            self.log('print', f"{pre}: released requests lock")

        self.log('debug', f"{pre}: threaded={threaded}")

        err_msg = ""
        try:
            server_address = (self.get_opt('bind'), self.get_opt('port'))
            ThreadingTCPServer.allow_reuse_address = True   # patching class: https://stackoverflow.com/a/15278302/90580
            self.server_instance = ThreadingTCPServer(server_address, ThreadedTCPRequestHandler)

            self.log('verbose', f"{pre}: (ip,port)={server_address}/{self.server_instance.server_address}")

            tct = threading.current_thread()
            if threaded:
                # Start a thread with the server -- that thread will then start one more thread for each request
                self.server_thread = threading.Thread(name="TransferThread", target=self.server_instance.serve_forever)
                self.server_thread.start()
                self.log('verbose', f"{pre}: server started from thread={tct.name} in thread={self.server_thread.name}")
            else:
                self.log('verbose', f"{pre}: starting server loop - using current thread={tct.name}")
                self.server_thread = tct
                self.server_instance.serve_forever()

        except (IOError, OSError, Exception) as ex:
            err_msg = f"{pre}: exception {ex}"
            self.log('print', err_msg)
            self.server_instance = self.server_thread = None

        return err_msg

    def stop_server(self):
        """ stop/pause transfer service server - callable also if not running to reset/prepare this app instance. """
        pre = "TransferServiceApp.stop_server"

        if requests_lock.locked():      # pragma: no cover
            requests_lock.release()
            self.log('print', f"{pre}: released requests lock")

        if getattr(self, 'server_instance', False) and getattr(self, 'server_thread', False):
            if threading.current_thread() == self.server_thread:    # pragma: no cover
                thread = threading.Thread(name="StopTransferService", target=self.server_instance.shutdown)
                thread.start()
                thread.join(timeout=SHUTDOWN_TIMEOUT)
                if thread.is_alive():
                    self.log('print', f"{pre}: server shutdown thread join timed out")
            else:
                self.server_instance.shutdown()
                self.server_thread.join(timeout=SHUTDOWN_TIMEOUT)
                if self.server_thread.is_alive():   # pragma: no cover
                    self.log('print', f"{pre}: server thread join timed out")
        self.server_instance = self.server_thread = None


if __name__ == '__main__':      # pragma: no cover
    # create app instance, parse command line args and start server
    server_app = service_factory()
    server_app.run_app()
    server_app.start_server()
