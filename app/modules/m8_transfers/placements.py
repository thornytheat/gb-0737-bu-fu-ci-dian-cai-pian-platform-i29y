from app.modules.m4_fit.choices import compatible


def rehome(pieces, target, orders, kerf):
    """把换下卷上的裁片按原裁切顺序逐片迁入换上卷的可用段。

    每片保留原裁片号，连同紧随刀口完整落入同一可用段；段内从前向后首次可容纳即落位。
    布种幅宽不符或无段可容纳的裁片记为欠料，返回 (新裁片, 欠料)。
    """
    by_id = {order["id"]: order for order in orders}
    segments = [[span["start"], span["end"]] for span in target["available"]]
    placed, short = [], []
    for piece in pieces:
        order = by_id[piece["order"]]
        need = order["length"] + kerf
        if not compatible(order, target):
            short.append({"piece": piece, "code": "NO_COMPATIBLE_ROLL"})
            continue
        spot = None
        for segment in segments:
            if segment[1] - segment[0] >= need:
                spot = segment[0]
                segment[0] += need
                break
        if spot is None:
            short.append({"piece": piece, "code": "SEGMENT_TOO_SHORT"})
            continue
        placed.append({**piece, "roll": target["id"], "start": spot, "end": spot + order["length"],
                       "kerf_start": spot + order["length"], "kerf_end": spot + need})
    return placed, short
