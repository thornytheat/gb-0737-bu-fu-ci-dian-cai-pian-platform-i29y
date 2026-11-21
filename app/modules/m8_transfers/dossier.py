from collections import Counter

from app.modules.m6_ledger.partition import partition
from app.modules.m7_slips.receipts import receipts
from app.modules.m8_transfers.placements import rehome
from app.reasons import MESSAGES

ZERO_LENGTHS = {"piece": 0, "blocked": 0, "kerf": 0, "unused": 0}


def recount(roll, placements, kerf):
    try:
        sums, spans = partition(roll, placements, kerf)
    except RuntimeError:
        return None, []
    return sums, spans


def build(document, out_roll, incoming, is_new, version, transfer_id, created):
    """基于已归档批次生成换卷调拨卷宗：只动换下卷，其余卷裁片原样保留。"""
    snapshot = document["snapshot"]
    kerf = snapshot["fit"]["kerf_mm"]
    orders = snapshot["fit"]["orders"]
    planning = snapshot["changeovers"]
    in_roll = incoming["id"]
    rolls = list(snapshot["zones"]["rolls"])
    if is_new:
        rolls = rolls + [incoming]
    by_roll = {roll["id"]: roll for roll in rolls}
    outgoing = by_roll[out_roll]

    moved_from = [plan for plan in planning["placements"] if plan["roll"] == out_roll]
    placed, short = rehome(moved_from, incoming, orders, kerf)
    others = [plan for plan in planning["placements"] if plan["roll"] != out_roll]
    new_placements = others + placed
    new_sequence = [in_roll if name == out_roll else name for name in planning["roll_sequence"]]

    books_before = {item["roll"]: item for item in snapshot["ledger"]["rolls"]}
    out_sums, out_spans = recount(outgoing, [], kerf)
    in_sums, in_spans = recount(incoming, placed, kerf)
    new_books = []
    for roll in rolls:
        roll_id = roll["id"]
        if roll_id == out_roll:
            new_books.append({**books_before[roll_id], "lengths": out_sums or {}, "spans": out_spans})
        elif roll_id == in_roll:
            new_books.append({"roll": in_roll, "length": incoming["length"], "held": False,
                              "source": incoming["source"]["ref"], "lengths": in_sums or {}, "spans": in_spans})
        else:
            new_books.append(books_before[roll_id])

    new_slips = receipts(rolls, {"placements": new_placements, "roll_sequence": new_sequence}, {"rolls": new_books})
    for slip in new_slips:
        slip["version"] = version
        slip["transfer"] = transfer_id
        if slip["roll"] == out_roll:
            slip["state"] = "换下"

    new_by_id = {plan["id"]: plan for plan in placed}
    short_by_id = {item["piece"]["id"]: item["code"] for item in short}
    pieces = []
    for plan in moved_from:
        moved = new_by_id.get(plan["id"])
        pieces.append({
            "id": plan["id"], "order": plan["order"], "length": plan["length"],
            "from": {"roll": out_roll, "start": plan["start"], "end": plan["end"]},
            "to": {"roll": in_roll, "start": moved["start"], "end": moved["end"], "kerf_end": moved["kerf_end"]}
            if moved else None,
            "status": "已调拨" if moved else "欠料",
            "reason": None if moved else {"code": short_by_id[plan["id"]], "message": MESSAGES[short_by_id[plan["id"]]]},
        })

    counts = Counter(plan["order"] for plan in new_placements)
    order_rows = []
    for row in planning["orders"]:
        after = counts[row["order"]]
        order_rows.append({"order": row["order"], "priority": row["priority"], "requested": row["requested"],
                           "planned_before": row["planned"], "planned_after": after,
                           "remaining_before": row["remaining"], "remaining_after": row["requested"] - after})

    slips_before = {slip["roll"]: slip for slip in snapshot["slips"]}
    slips_after = {slip["roll"]: slip for slip in new_slips}
    books_after = {item["roll"]: item for item in new_books}
    roll_rows = []
    for roll in rolls:
        roll_id = roll["id"]
        before = slips_before.get(roll_id, {"state": "未入册", "sequence": None})
        lengths_before = books_before.get(roll_id, {"lengths": ZERO_LENGTHS})["lengths"]
        after = slips_after[roll_id]
        entry = {"roll": roll_id, "state_before": before["state"], "state_after": after["state"],
                 "sequence_before": before["sequence"], "sequence_after": after["sequence"],
                 "length": roll["length"], "lengths_before": lengths_before,
                 "lengths_after": books_after[roll_id]["lengths"],
                 "unused_delta": (books_after[roll_id]["lengths"] or {}).get("unused", 0) - lengths_before["unused"]}
        if roll_id in (out_roll, in_roll):
            entry["spans_after"] = books_after[roll_id]["spans"]
        roll_rows.append(entry)

    totals_before = snapshot["ledger"]["totals"]
    totals_after = {key: sum((item["lengths"] or {}).get(key, 0) for item in new_books)
                    for key in ("piece", "blocked", "kerf", "unused")}
    totals_after["length"] = sum(item["length"] for item in new_books)
    totals_after["delta"] = totals_after["length"] - sum(totals_after[key] for key in ("piece", "blocked", "kerf", "unused"))

    lengths = books_after[in_roll]["lengths"] or {}
    checks = [
        {"code": "BASE_BALANCED", "label": "旧版账目对平",
         "ok": totals_before["delta"] == 0,
         "detail": f"旧版差额 {totals_before['delta']} mm"},
        {"code": "MOVED_ANY", "label": "换上卷承接裁片",
         "ok": bool(placed),
         "detail": f"承接 {len(placed)} 片，欠料 {len(short)} 片"},
        {"code": "PIECES_CONSERVED", "label": "裁片去向守恒",
         "ok": len(placed) + len(short) == len(moved_from)
         and sorted([*new_by_id, *short_by_id]) == sorted(plan["id"] for plan in moved_from),
         "detail": f"原卷 {len(moved_from)} 片 = 调拨 {len(placed)} + 欠料 {len(short)}"},
        {"code": "ORDERS_CONSERVED", "label": "工单欠料守恒",
         "ok": all(row["planned_after"] + row["remaining_after"] == row["requested"] and row["planned_after"] >= 0
                   for row in order_rows),
         "detail": "各工单 已排 + 待补 = 需求"},
        {"code": "IN_ROLL_BALANCED", "label": "新卷分项守恒",
         "ok": in_sums is not None and sum(in_sums.values()) == incoming["length"]
         and in_sums["blocked"] == incoming["blocked_mm"],
         "detail": f"卷长 {incoming['length']} = 合格 {lengths.get('piece', 0)}"
                   f" + 禁切 {lengths.get('blocked', 0)}"
                   f" + 切口 {lengths.get('kerf', 0)}"
                   f" + 未用 {lengths.get('unused', 0)}"},
        {"code": "OUT_ROLL_CLEARED", "label": "换下卷腾空",
         "ok": out_sums is not None and out_sums["piece"] == 0 and out_sums["kerf"] == 0
         and not any(plan["roll"] == out_roll for plan in new_placements),
         "detail": f"{out_roll} 余量 {(books_after[out_roll]['lengths'] or {}).get('unused', 0)} mm 回库"},
        {"code": "BATCH_BALANCED", "label": "整批差额为零",
         "ok": totals_after["delta"] == 0,
         "detail": f"换卷后差额 {totals_after['delta']} mm"},
        {"code": "OTHERS_UNTOUCHED", "label": "他卷裁片未动",
         "ok": [plan for plan in new_placements if plan["roll"] not in (out_roll, in_roll)]
         == [plan for plan in planning["placements"] if plan["roll"] not in (out_roll, in_roll)],
         "detail": f"{len(others)} 片保持原卷原段"},
    ]

    return {
        "manifest": {"id": transfer_id, "run_id": document["manifest"]["id"], "version": version,
                     "out_roll": out_roll, "in_roll": in_roll, "new_roll": is_new,
                     "sample": document["manifest"]["sample"], "kerf_mm": kerf,
                     "rules": document["manifest"]["rules"], "created_at": created,
                     "moved": len(placed), "short": len(short)},
        "incoming": {"id": in_roll, "fabric": incoming["fabric"], "width": incoming["width"],
                     "length": incoming["length"], "new_roll": is_new},
        "pieces": pieces, "orders": order_rows, "rolls": roll_rows,
        "totals": {"before": totals_before, "after": totals_after},
        "checks": checks, "slips": new_slips,
    }
