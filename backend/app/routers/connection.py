"""连接候选接口：数据源接入与数据集管理共用的候选检索与绑定过程。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas import ActionResult, BindSourcePayload, PageResult
from app.security import Operator, current_operator
from app.services.connection import connection_service

router = APIRouter(prefix="/api/connections", tags=["连接候选"])


@router.get("/candidates", response_model=PageResult[dict])
def list_candidates(
    config_no: str | None = Query(default=None, description="按配置编号模糊检索"),
    conn_type: str | None = Query(default=None, description="按连接类型模糊检索"),
    address: str | None = Query(default=None, description="按接入地址模糊检索"),
    owner: str | None = Query(default=None, description="按负责人精确定位"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1),
    operator: Operator = Depends(current_operator),
) -> PageResult[dict]:
    """连接候选检索：类型/地址可组合，负责人精确定位，按身份裁决可见范围。

    越权检索返回 403 且响应体不含任何匹配数量信息。
    """
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = connection_service.search_candidates(
        operator,
        config_no=config_no,
        conn_type=conn_type,
        address=address,
        owner=owner,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/datastore/{datastore_id}/bind", response_model=ActionResult)
def bind_datastore(
    datastore_id: int,
    payload: BindSourcePayload,
    operator: Operator = Depends(current_operator),
) -> ActionResult:
    """把连接候选绑定到数据集；重名冲突返回 409 并带上候选供用户确认。"""
    entry, result = connection_service.bind_to_datastore(
        operator,
        datastore_id,
        source_id=payload.source_id,
        source_name=payload.source_name,
        confirmed=payload.confirmed,
    )
    if result.get("ok"):
        return ActionResult(ok=True, message=result["message"], entry=entry)
    if result.get("code") == "conflict":
        # detail 携带候选列表，前端据此进入“确认候选”流程，而不是静默挑一条连接。
        raise HTTPException(
            status_code=409,
            detail={"message": result["message"], "candidates": result["candidates"]},
        )
    if result.get("code") == "disconnected":
        return ActionResult(ok=False, message=result["message"], entry=result.get("candidate"))
    status_code = 404 if result.get("code") == "not_found" else 400
    raise HTTPException(status_code=status_code, detail=result["message"])


@router.get("/datastore/{datastore_id}/binding")
def get_binding(
    datastore_id: int,
    operator: Operator = Depends(current_operator),
) -> dict:
    """查看数据集的来源绑定状态与连接实时状态（绑定身份快照不变）。"""
    return connection_service.binding_status(datastore_id)
