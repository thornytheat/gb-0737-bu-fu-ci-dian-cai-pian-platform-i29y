from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, StringConstraints, conint

from app.modules.m8_transfers.archiving import issue

router = APIRouter(prefix="/api", tags=["换卷调拨"])
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class NewRoll(BaseModel):
    id: Name
    fabric: Name
    width: conint(strict=True, ge=1, le=4000)
    length: conint(strict=True, ge=1, le=1_000_000)


class TransferRequest(BaseModel):
    run_id: str
    out_roll: Name
    in_roll: Name | NewRoll


@router.post("/transfers", status_code=201)
def create(payload: TransferRequest, request: Request, response: Response):
    manifest, reused = issue(request.app.state.archive, payload.run_id, payload.out_roll, payload.in_roll)
    if reused:
        response.status_code = 200
    return {"manifest": manifest, "reused": reused}


@router.get("/transfers")
def listed(request: Request, run_id: str | None = None):
    return {"transfers": request.app.state.archive.transfers(run_id)}


@router.get("/transfers/{transfer_id}")
def archived(transfer_id: str, request: Request):
    return request.app.state.archive.read_transfer(transfer_id)
