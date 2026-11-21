from app.archive import lookup_transfer, save_transfer, transfer_count
from app.manifest import hash_payload, timestamp
from app.modules.m8_transfers.dossier import build
from app.reasons import FabricError


def resolve_incoming(snapshot, spec):
    """把换上参数归一为卷册条目：在册卷号直接取用，新卷按已验合格无禁切入册。"""
    rolls = {roll["id"]: roll for roll in snapshot["zones"]["rolls"]}
    if isinstance(spec, str):
        if spec not in rolls:
            raise FabricError("IN_ROLL_UNKNOWN")
        if rolls[spec]["held"]:
            raise FabricError("IN_ROLL_HELD")
        return rolls[spec], False
    if spec.id in rolls:
        raise FabricError("IN_ROLL_DUPLICATE")
    return {"id": spec.id, "fabric": spec.fabric, "width": spec.width, "length": spec.length,
            "blocked": [], "available": [{"start": 0, "end": spec.length}], "held": False,
            "hold_refs": [], "blocked_mm": 0, "overlap": 0,
            "source": {"file": "换卷调拨", "line": 0, "end": 0, "cells": (), "ref": "换卷调拨入册"}}, True


def issue(archive, run_id, out_roll, spec):
    """签发换卷调拨卷宗。同一调拨重跑复用原卷宗；未对平则拒绝且不动旧版签条。"""
    document = archive.read(run_id)
    snapshot = document["snapshot"]
    in_roll = spec if isinstance(spec, str) else spec.id
    if out_roll == in_roll:
        raise FabricError("TRANSFER_SAME_ROLL")
    used = {plan["roll"] for plan in snapshot["changeovers"]["placements"]}
    if out_roll not in used:
        raise FabricError("OUT_ROLL_UNUSED")
    incoming, is_new = resolve_incoming(snapshot, spec)
    if not is_new and in_roll in used:
        raise FabricError("IN_ROLL_BUSY")

    rules = document["manifest"]["rules"]
    key = in_roll if not is_new else {"id": in_roll, "fabric": incoming["fabric"],
                                      "width": incoming["width"], "length": incoming["length"]}
    transfer_id = hash_payload({"run": run_id, "out": out_roll, "in": key, "rules": rules})
    with archive.write() as db:
        current = lookup_transfer(db, transfer_id)
        if current:
            return current["manifest"], True
        dossier = build(document, out_roll, incoming, is_new, transfer_count(db, run_id) + 2, transfer_id, timestamp())
        if not all(check["ok"] for check in dossier["checks"]):
            raise FabricError("TRANSFER_UNBALANCED",
                              details={"checks": dossier["checks"], "pieces": dossier["pieces"]})
        save_transfer(db, dossier)
        return dossier["manifest"], False
