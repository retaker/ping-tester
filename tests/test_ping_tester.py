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


class TestAlertState:
    def test_initial_normal(self):
        from ping_tester import AlertState
        s = AlertState()
        assert not s.in_fail_group
        assert s.fails == 0

    def test_isolated_fail_no_alert(self):
        from ping_tester import AlertState
        s = AlertState()
        result = s.record_fail()
        assert result is None  # fail=1, no alert
        # Need 3 OKs to reset fails
        for _ in range(3):
            s.record_success()
        assert s.fails == 0
        assert s.successes == 0

    def test_two_fails_triggers_beep_1(self):
        from ping_tester import AlertState
        s = AlertState()
        s.record_fail()
        result = s.record_fail()
        assert result == 'beep_1'
        # fails stays at 2, not reset by 1-2 OKs
        s.record_success()
        assert s.fails == 2  # not reset yet
        s.record_success()
        assert s.fails == 2  # still not reset
        s.record_success()
        assert s.fails == 0  # reset after 3rd OK
        assert s.successes == 0

    def test_five_fails_triggers_beep_3_and_silences(self):
        from ping_tester import AlertState
        s = AlertState()
        for _ in range(4):
            s.record_fail()
        result = s.record_fail()  # 5th fail
        assert result == 'beep_3'
        assert s.silenced is True

    def test_silenced_stays_silent(self):
        from ping_tester import AlertState
        s = AlertState()
        for _ in range(5):
            s.record_fail()
        assert s.silenced
        result = s.record_fail()  # 6th fail
        assert result is None

    def test_recovery_resets_silenced(self):
        from ping_tester import AlertState
        s = AlertState()
        for _ in range(5):
            s.record_fail()
        assert s.silenced
        for _ in range(3):
            s.record_success()
        assert not s.silenced
        assert s.fails == 0

    def test_fail_then_success_before_threshold(self):
        from ping_tester import AlertState
        s = AlertState()
        s.record_fail()  # fail=1
        # 1 OK does not reset — need 3
        s.record_success()
        assert s.fails == 1  # not reset
        # fail again before 3 OKs — continues counting
        assert s.record_fail() == 'beep_1'  # fail=2, triggers alert

    def test_silenced_one_ok_does_not_reset_fails(self):
        from ping_tester import AlertState
        s = AlertState()
        for _ in range(5):
            s.record_fail()
        assert s.silenced
        assert s.fails == 5
        s.record_success()
        assert s.silenced  # still silenced
        assert s.fails == 5  # fails NOT reset after 1 OK
        assert s.successes == 1

    def test_silenced_three_oks_reset_everything(self):
        from ping_tester import AlertState
        s = AlertState()
        for _ in range(5):
            s.record_fail()
        assert s.silenced
        s.record_success()
        assert s.silenced  # still silenced after 1
        s.record_success()
        assert s.silenced  # still silenced after 2
        s.record_success()
        assert not s.silenced  # unsilenced after 3
        assert s.fails == 0
        assert s.successes == 0
