import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from fastapi.testclient import TestClient

from app.main import build_application

NEW_ROLL = {"id": "R-101", "fabric": "斜纹棉", "width": 1550, "length": 1800}


def archive_run(client, sample="dirty", kerf=5):
    return client.post("/api/runs", json={"sample": sample, "kerf_mm": kerf}).json()["manifest"]


def swap(client, run_id, out="R-002", into=NEW_ROLL):
    return client.post("/api/transfers", json={"run_id": run_id, "out_roll": out, "in_roll": into})


def test_swap_rehomes_pieces_and_reissues_whole_batch_at_one_version(client):
    run_id = archive_run(client)["id"]
    created = swap(client, run_id)
    assert created.status_code == 201
    manifest = created.json()["manifest"]
    assert (manifest["version"], manifest["moved"], manifest["short"], manifest["new_roll"]) == (2, 3, 0, True)
    assert manifest["run_id"] == run_id

    dossier = client.get(f"/api/transfers/{manifest['id']}").json()
    assert [(p["id"], p["to"]["roll"], p["to"]["start"], p["to"]["end"], p["to"]["kerf_end"], p["status"])
            for p in dossier["pieces"]] == [
        ("C001/01", "R-101", 0, 620, 625, "已调拨"),
        ("C001/02", "R-101", 625, 1245, 1250, "已调拨"),
        ("C002/03", "R-101", 1250, 1780, 1785, "已调拨"),
    ]
    assert all(p["reason"] is None for p in dossier["pieces"])
    orders = {row["order"]: row for row in dossier["orders"]}
    assert (orders["C001"]["planned_after"], orders["C001"]["remaining_after"]) == (2, 0)
    assert (orders["C004"]["planned_after"], orders["C004"]["remaining_after"]) == (1, 1)

    rolls = {row["roll"]: row for row in dossier["rolls"]}
    assert (rolls["R-002"]["state_after"], rolls["R-002"]["sequence_after"]) == ("换下", None)
    assert (rolls["R-002"]["lengths_after"]["unused"], rolls["R-002"]["unused_delta"]) == (1789, 1785)
    assert (rolls["R-101"]["state_before"], rolls["R-101"]["state_after"], rolls["R-101"]["sequence_after"]) == ("未入册", "待裁", 2)
    assert rolls["R-101"]["lengths_after"] == {"piece": 1770, "blocked": 0, "kerf": 15, "unused": 15}
    assert rolls["R-001"]["lengths_after"] == rolls["R-001"]["lengths_before"]

    after = dossier["totals"]["after"]
    assert (after["length"], after["delta"]) == (10425, 0)
    assert after["length"] - dossier["totals"]["before"]["length"] == 1800
    assert all(check["ok"] for check in dossier["checks"]) and len(dossier["checks"]) == 8

    slips = {slip["roll"]: slip for slip in dossier["slips"]}
    assert {slip["version"] for slip in slips.values()} == {2}
    assert [(slips[key]["state"], slips[key]["sequence"], len(slips[key]["pieces"]))
            for key in ("R-001", "R-002", "R-003", "R-004", "R-005", "R-101")] == [
        ("待裁", 1, 4), ("换下", None, 0), ("封存", None, 0), ("留存", None, 0), ("待裁", 3, 1), ("待裁", 2, 3),
    ]
    assert [piece["id"] for piece in slips["R-101"]["pieces"]] == ["C001/01", "C001/02", "C002/03"]

    old = client.get(f"/api/runs/{run_id}").json()["snapshot"]
    assert [(s["state"], len(s["pieces"])) for s in old["slips"] if s["roll"] == "R-002"] == [("待裁", 3)]
    assert "version" not in old["slips"][0]


def test_shorter_new_roll_turns_overflow_into_shortage_and_still_balances(client):
    run_id = archive_run(client)["id"]
    short_roll = {"id": "R-102", "fabric": "斜纹棉", "width": 1550, "length": 1200}
    created = swap(client, run_id, into=short_roll)
    assert created.status_code == 201
    dossier = client.get(f"/api/transfers/{created.json()['manifest']['id']}").json()
    pieces = {p["id"]: p for p in dossier["pieces"]}
    assert (pieces["C001/01"]["to"]["start"], pieces["C001/01"]["to"]["end"]) == (0, 620)
    assert pieces["C001/02"]["to"] is None and pieces["C001/02"]["status"] == "欠料"
    assert pieces["C001/02"]["reason"]["code"] == "SEGMENT_TOO_SHORT"
    assert (pieces["C002/03"]["to"]["start"], pieces["C002/03"]["to"]["end"]) == (625, 1155)
    orders = {row["order"]: row for row in dossier["orders"]}
    assert (orders["C001"]["planned_after"], orders["C001"]["remaining_after"]) == (1, 1)
    after = dossier["totals"]["after"]
    assert (after["piece"], after["unused"], after["delta"]) == (3470, 3388, 0)


def test_same_transfer_rerun_never_issues_another_slip_version(client):
    run_id = archive_run(client)["id"]
    first = swap(client, run_id)
    assert first.status_code == 201
    again = swap(client, run_id)
    assert again.status_code == 200 and again.json() == {"manifest": first.json()["manifest"], "reused": True}
    listed = client.get("/api/transfers", params={"run_id": run_id}).json()["transfers"]
    assert [item["version"] for item in listed] == [2]

    other = swap(client, run_id, out="R-005", into={"id": "R-103", "fabric": "帆布", "width": 1300, "length": 625})
    assert other.status_code == 201 and other.json()["manifest"]["version"] == 3
    listed = client.get("/api/transfers", params={"run_id": run_id}).json()["transfers"]
    assert [item["version"] for item in listed] == [3, 2]
    assert swap(client, run_id).json()["manifest"]["version"] == 2


def test_unbalanced_base_is_refused_and_old_slips_survive(client, settings):
    run_id = archive_run(client)["id"]
    with closing(sqlite3.connect(settings.database)) as db:
        document = json.loads(db.execute("SELECT document FROM runs WHERE id=?", (run_id,)).fetchone()[0])
        document["snapshot"]["ledger"]["totals"]["delta"] = 7
        db.execute("UPDATE runs SET document=? WHERE id=?", (json.dumps(document), run_id))
        db.commit()
    before = client.get(f"/api/export/{run_id}").content
    response = swap(client, run_id)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "TRANSFER_UNBALANCED")
    failed = {check["code"] for check in response.json()["error"]["details"]["checks"] if not check["ok"]}
    assert failed == {"BASE_BALANCED"}
    assert client.get("/api/transfers", params={"run_id": run_id}).json()["transfers"] == []
    assert client.get(f"/api/export/{run_id}").content == before
    with closing(sqlite3.connect(settings.database)) as db:
        assert db.execute("SELECT COUNT(*) FROM transfers").fetchone()[0] == 0


def test_incompatible_reserved_roll_moves_nothing_and_is_refused(client):
    run_id = archive_run(client)["id"]
    response = swap(client, run_id, into="R-004")
    assert (response.status_code, response.json()["error"]["code"]) == (422, "TRANSFER_UNBALANCED")
    details = response.json()["error"]["details"]
    failed = {check["code"] for check in details["checks"] if not check["ok"]}
    assert failed == {"MOVED_ANY"}
    assert {piece["reason"]["code"] for piece in details["pieces"]} == {"NO_COMPATIBLE_ROLL"}
    assert client.get("/api/transfers", params={"run_id": run_id}).json()["transfers"] == []


def test_roll_choice_validation(client):
    run_id = archive_run(client)["id"]
    cases = [
        ({"out_roll": "R-002", "in_roll": "R-002"}, "TRANSFER_SAME_ROLL"),
        ({"out_roll": "R-004", "in_roll": NEW_ROLL}, "OUT_ROLL_UNUSED"),
        ({"out_roll": "R-003", "in_roll": NEW_ROLL}, "OUT_ROLL_UNUSED"),
        ({"out_roll": "R-999", "in_roll": NEW_ROLL}, "OUT_ROLL_UNUSED"),
        ({"out_roll": "R-002", "in_roll": "R-999"}, "IN_ROLL_UNKNOWN"),
        ({"out_roll": "R-002", "in_roll": "R-003"}, "IN_ROLL_HELD"),
        ({"out_roll": "R-002", "in_roll": "R-001"}, "IN_ROLL_BUSY"),
        ({"out_roll": "R-002", "in_roll": {**NEW_ROLL, "id": "R-004"}}, "IN_ROLL_DUPLICATE"),
    ]
    for body, code in cases:
        response = client.post("/api/transfers", json={"run_id": run_id, **body})
        assert (response.status_code, response.json()["error"]["code"]) == (422, code), body
    assert client.get("/api/transfers", params={"run_id": run_id}).json()["transfers"] == []


def test_transfer_and_run_not_found(client):
    missing = client.post("/api/transfers", json={"run_id": "none", "out_roll": "R-002", "in_roll": NEW_ROLL})
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "RUN_UNKNOWN")
    assert (client.get("/api/transfers/none").status_code,
            client.get("/api/transfers/none").json()["error"]["code"]) == (404, "TRANSFER_UNKNOWN")


def test_new_roll_spec_is_validated(client):
    run_id = archive_run(client)["id"]
    for bad in ({**NEW_ROLL, "length": 0}, {**NEW_ROLL, "length": 1000001}, {**NEW_ROLL, "width": 0},
                {**NEW_ROLL, "width": 4001}, {**NEW_ROLL, "id": " "}, {**NEW_ROLL, "fabric": ""},
                {**NEW_ROLL, "length": 1799.5}):
        response = swap(client, run_id, into=bad)
        assert (response.status_code, response.json()["error"]["code"]) == (422, "FORM_INVALID"), bad
    assert client.get("/api/transfers", params={"run_id": run_id}).json()["transfers"] == []


def test_concurrent_identical_transfers_stay_single_version(client):
    run_id = archive_run(client)["id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: swap(client, run_id), range(4)))
    assert sorted(response.status_code for response in responses) == [200, 200, 200, 201]
    assert len({response.json()["manifest"]["id"] for response in responses}) == 1
    listed = client.get("/api/transfers", params={"run_id": run_id}).json()["transfers"]
    assert [item["version"] for item in listed] == [2]


def test_transfer_dossier_survives_source_removal_and_restart(client, settings):
    run_id = archive_run(client)["id"]
    manifest = swap(client, run_id).json()["manifest"]
    for name in ("dirty-rolls.csv", "dirty-defects.csv", "dirty-orders.csv"):
        (settings.samples / name).unlink()
    with TestClient(build_application(settings)) as restarted:
        dossier = restarted.get(f"/api/transfers/{manifest['id']}")
        assert dossier.status_code == 200 and dossier.json()["manifest"] == manifest
        listed = restarted.get("/api/transfers", params={"run_id": run_id}).json()["transfers"]
        assert [item["id"] for item in listed] == [manifest["id"]]
        assert [item["id"] for item in restarted.get("/api/transfers").json()["transfers"]] == [manifest["id"]]


def test_workbench_offers_swap_controls(client):
    home = client.get("/")
    assert all(word in home.text for word in ("换卷调拨", "换下卷", "换上卷", "new-roll-fields"))
