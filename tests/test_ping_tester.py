import pytest
from ping_tester import host_label, classify_result


class TestHostLabel:
    def test_simple_domain(self):
        assert host_label("baidu.com") == "baidu"

    def test_subdomain(self):
        assert host_label("ipv6.google.com") == "google"

    def test_ipv4_address(self):
        assert host_label("8.8.8.8") == "8.8.8.8"

    def test_ipv6_address(self):
        assert host_label("2001:4860:4860::8888") == "2001:4860"

    def test_single_label(self):
        assert host_label("localhost") == "localhost"


class TestClassifyResult:
    def test_ok(self):
        assert classify_result(True, 45.0, 200) == 'OK'

    def test_slow(self):
        assert classify_result(True, 320.0, 200) == 'SLOW'

    def test_slow_at_threshold(self):
        # exactly at threshold is OK (not SLOW)
        assert classify_result(True, 200.0, 200) == 'OK'

    def test_fail(self):
        assert classify_result(False, 0, 200) == 'FAIL'

    def test_fail_ignores_latency(self):
        # FAIL always takes priority over latency check
        assert classify_result(False, 999.0, 200) == 'FAIL'
