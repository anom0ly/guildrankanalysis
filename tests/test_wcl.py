from guildpulls.wcl import WCLClient, parse_fights


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status_code, self._body, self.headers, self.text = status, body, headers or {}, ""

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        if "oauth" in url:
            return FakeResponse(200, {"access_token": "t", "expires_in": 3600})
        return self.responses.pop(0)


def rate(spent, reset=1200):
    return {"rateLimitData": {"limitPerHour": 18000, "pointsSpentThisHour": spent, "pointsResetIn": reset}}


def client(responses, reserve=500):
    sleeps = []
    c = WCLClient("id", "secret", session=FakeSession(responses), sleep=sleeps.append, clock=lambda: 0,
                  reserve=reserve)
    return c, sleeps


def test_pauses_until_reset_when_points_run_low():
    c, sleeps = client([FakeResponse(200, {"data": {"x": 1, **rate(17_600, reset=900)}}),
                        FakeResponse(200, {"data": {"x": 2, **rate(10, reset=3590)}})])
    c.query("x")
    assert sleeps == [] and c.rate.remaining == 400
    c.query("x")
    assert sleeps == [905]
    assert c.rate.remaining == 17_990


def test_no_pause_with_budget_left():
    c, sleeps = client([FakeResponse(200, {"data": {"x": 1, **rate(100)}})] * 3)
    for _ in range(3):
        c.query("x")
    assert sleeps == []


def test_retries_after_429():
    c, sleeps = client([FakeResponse(429, {}, {"Retry-After": "30"}),
                        FakeResponse(200, {"data": {"x": 1, **rate(5)}})])
    assert c.query("x")["x"] == 1
    assert sleeps == [30]


def test_points_used_tracks_spend():
    c, _ = client([FakeResponse(200, {"data": rate(10)}), FakeResponse(200, {"data": rate(35)})])
    c.query("x"); c.query("x")
    assert c.points_used == 35


def test_query_includes_rate_limit_fields_and_variables():
    c, _ = client([FakeResponse(200, {"data": {"guildData": {"guild": {"id": 7}}, **rate(1)}})])
    assert c.find_guild("Échø", "tarren-mill", "eu") == 7
    sent = c.session.calls[-1][1]["json"]
    assert "rateLimitData" in sent["query"] and "$name: String" in sent["query"]
    assert sent["variables"] == {"name": "Échø", "realm": "tarren-mill", "region": "eu"}


def test_parse_fights_makes_times_absolute():
    rep = {"startTime": 1_000_000, "fights": [
        {"id": 3, "encounterID": 3470, "startTime": 5000, "endTime": 65000, "kill": True,
         "averageItemLevel": 711.2, "bossPercentage": 0, "lastPhase": 2},
        {"id": 4, "encounterID": 0, "startTime": 0, "endTime": 1, "kill": False},
    ]}
    [p] = parse_fights("ABC", rep)
    assert (p.start_ms, p.end_ms, p.kill, p.item_level, p.fight_id) == (1_005_000, 1_065_000, True, 711.2, 3)


def test_enrich_reports_pages_death_events_and_names_killers():
    report = {"fights": [{"id": 4, "startTime": 0, "endTime": 9, "fightPercentage": 12.5, "friendlyPlayers": [7]}],
              "masterData": {"actors": [{"id": 7, "name": "Ann", "server": None}],
                             "abilities": [{"gameID": 1284209, "name": "Living Venom"}]},
              "events": {"data": [{"type": "death", "fight": 4, "timestamp": 5, "killingAbilityGameID": 1284209},
                                  {"type": "applybuff", "fight": 4}], "nextPageTimestamp": 6}}
    page2 = {"report": {"events": {"data": [{"type": "death", "fight": 4, "timestamp": 7}], "nextPageTimestamp": None}}}
    c, _ = client([FakeResponse(200, {"data": {"reportData": {"r0": report}, **rate(10)}}),
                   FakeResponse(200, {"data": {"reportData": page2, **rate(12)}})])
    got = c.enrich_reports([("abc", [4])])["abc"]
    assert got["actors"] == {7: ("Ann", "")}
    assert got["deaths"] == [{"fight": 4, "timestamp": 5, "killingAbilityGameID": 1284209,
                              "killingAbilityName": "Living Venom"},
                             {"fight": 4, "timestamp": 7, "killingAbilityGameID": None, "killingAbilityName": None}]
    assert "startTime: 6.0" in c.session.calls[-1][1]["json"]["query"]


def test_report_without_events_is_unreadable_not_a_crash():
    gone = {"fights": [], "masterData": None, "events": None}
    ok = {"fights": [], "masterData": {"actors": [], "abilities": []}, "events": {"data": [], "nextPageTimestamp": None}}
    c, _ = client([FakeResponse(200, {"data": {"reportData": {"r0": gone, "r1": None, "r2": ok}, **rate(10)}})])
    got = c.enrich_reports([("a", [1]), ("b", [1]), ("c", [1])])
    assert got["a"] == {"unreadable": True} and got["b"] == {"unreadable": True}
    assert got["c"]["deaths"] == []


def test_parallel_queries_pause_once_for_the_budget():
    import threading
    c, sleeps = client([])
    c.rate.spent = 17_900
    threads = [threading.Thread(target=c.wait_for_budget) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(sleeps) == 1
