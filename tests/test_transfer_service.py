""" transfer service unit tests. """
import datetime

from ae.transfer_service import TRANSFER_KWARGS_LINE_END_CHAR, transfer_kwargs_from_literal, transfer_kwargs_literal


class TestHelpers:
    def test_transfer_service_from_literal_basics(self):
        assert transfer_kwargs_from_literal("{}") == dict()

    def test_transfer_service_from_literal_date_time(self):
        assert transfer_kwargs_from_literal("{'_date': (1999, 1, 10)}") == dict(_date=datetime.datetime(1999, 1, 10))

    def test_transfer_kwargs_literal_basics(self):
        assert transfer_kwargs_literal(dict()) == "{}" + TRANSFER_KWARGS_LINE_END_CHAR

    def test_transfer_kwargs_literal_date_time(self):
        test_time = datetime.datetime.now()
        assert transfer_kwargs_literal(dict(_time=test_time)) == \
               "{'_time': " + str(tuple(test_time.timetuple())[:7]) + "}" + TRANSFER_KWARGS_LINE_END_CHAR
