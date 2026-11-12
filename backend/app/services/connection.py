"""连接候选服务：数据源接入与数据集管理共用的候选选择过程。

候选条目以单条接入配置为最小单位——同址多负责人、同负责人多地址都是不同候选，
因此分页与计数直接基于 source 表行，天然不会被合并。
"""
from __future__ import annotations

from typing import Any

from app.security import Operator, assert_can_bind, assert_can_search
from app.store import store

MODULE = "source"
DISCONNECTED = "已断开"
CONNECTED = "已连接"

# 候选对外暴露的字段：认证凭证等敏感信息不进候选集。
CANDIDATE_FIELDS = ("id", "配置编号", "连接类型", "接入地址", "负责人", "status")


def _contains(row: dict[str, Any], field: str, keyword: str) -> bool:
    return keyword in str(row.get(field) or "")


class ConnectionService:
    def search_candidates(
        self,
        operator: Operator,
        *,
        config_no: str | None = None,
        conn_type: str | None = None,
        address: str | None = None,
        owner: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """按身份裁决后的连接候选检索。

        - 连接类型与接入地址可组合模糊搜索，配置编号同样走包含匹配；
        - 负责人为精确定位；普通成员不指定负责人时也只能看到自己负责的连接；
        - 按 id 稳定排序后再分页，翻页不会重复或漏条。
        """
        owner = owner.strip() if owner else None
        # 授权先于过滤执行，越权请求在接触任何数据前就被拒绝。
        assert_can_search(operator, owner)
        effective_owner = owner if owner else (None if operator.is_admin else operator.name)

        rows = list(store.rows(MODULE))
        if config_no:
            rows = [row for row in rows if _contains(row, "配置编号", config_no)]
        if conn_type:
            rows = [row for row in rows if _contains(row, "连接类型", conn_type)]
        if address:
            rows = [row for row in rows if _contains(row, "接入地址", address)]
        if effective_owner is not None:
            rows = [row for row in rows if str(row.get("负责人") or "") == effective_owner]

        # 稳定排序：id 唯一且不可变，保证同一条件下翻页结果不重复。
        rows.sort(key=lambda row: int(row.get("id", 0)))
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = rows[start:start + size]
        return [self._to_candidate(row) for row in page_rows], total

    def get_candidate(self, source_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, source_id)
        if row is None:
            return None
        return self._to_candidate(row)

    def resolve_by_name(
        self, operator: Operator, name: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """兼容历史上只有名称的来源记录：按配置编号/接入地址解析候选。

        返回 (唯一匹配, 候选列表)。匹配不唯一时调用方必须让用户确认，
        不能静默替用户挑一条。
        """
        keyword = name.strip()
        if not keyword:
            return None, []
        candidates, _ = self.search_candidates(
            operator, config_no=keyword, page=1, size=200
        )
        # 配置编号没命中再尝试接入地址，两个口径共用同一候选集入口。
        if not candidates:
            candidates, _ = self.search_candidates(
                operator, address=keyword, page=1, size=200
            )
        if len(candidates) == 1:
            return candidates[0], candidates
        return None, candidates

    def bind_to_datastore(
        self,
        operator: Operator,
        datastore_id: int,
        *,
        source_id: int | None = None,
        source_name: str | None = None,
        confirmed: bool = False,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """把连接候选绑定到数据集，返回 (数据集记录, 结果描述)。

        结果描述约定：
        - ok=True 绑定成功；
        - ok=False + conflict 候选列表：重名冲突，需要用户确认；
        - ok=False 且无 conflict：权限/状态类拒绝。
        """
        datastore = store.find("datastore", datastore_id)
        if datastore is None:
            return None, {"ok": False, "code": "not_found", "message": f"数据集定义 {datastore_id} 不存在或已归档"}

        candidate: dict[str, Any] | None = None
        if source_id is not None:
            candidate = self.get_candidate(int(source_id))
            if candidate is None:
                return None, {"ok": False, "code": "not_found", "message": "所选连接候选不存在或已归档"}
        elif source_name:
            matched, choices = self.resolve_by_name(operator, source_name)
            if matched is None:
                if not choices:
                    return None, {"ok": False, "code": "not_found", "message": "未找到与来源名称匹配的连接候选"}
                if not confirmed:
                    return None, {
                        "ok": False,
                        "code": "conflict",
                        "message": f"来源名称匹配到 {len(choices)} 个连接，请确认具体候选后再绑定",
                        "candidates": choices,
                    }
                # confirmed 必须配合 source_id 使用，避免名称口径再次歧义。
                return None, {"ok": False, "code": "conflict", "message": "重名冲突需指定具体连接编号后确认", "candidates": choices}
            candidate = matched
        else:
            return None, {"ok": False, "code": "bad_request", "message": "缺少连接候选编号或来源名称"}

        owner = str(candidate.get("负责人") or "")
        # 授权不通过会直接抛 403，不回显任何命中信息。
        assert_can_bind(operator, owner)

        if candidate["status"] == DISCONNECTED:
            return None, {
                "ok": False,
                "code": "disconnected",
                "message": "连接已断开，不允许新的绑定；请选择其他可用连接",
                "candidate": candidate,
            }

        self._write_snapshot(datastore, candidate)
        return datastore, {"ok": True, "code": "bound", "message": "来源连接已绑定", "candidate": candidate}

    def binding_status(self, datastore_id: int) -> dict[str, Any]:
        """回显数据集已绑定连接的当前状态；连接后续断开也保留绑定时的身份快照。"""
        datastore = store.find("datastore", datastore_id)
        if datastore is None:
            return {"bound": False, "message": f"数据集定义 {datastore_id} 不存在或已归档"}
        source_id = datastore.get("来源连接ID")
        if not source_id:
            return {"bound": False, "legacy_name": datastore.get("来源表名") or ""}
        live = store.find(MODULE, int(source_id))
        return {
            "bound": True,
            "snapshot": {
                "source_id": source_id,
                "配置编号": datastore.get("来源配置编号"),
                "连接类型": datastore.get("来源连接类型"),
                "接入地址": datastore.get("来源接入地址"),
                "负责人": datastore.get("来源负责人"),
                "绑定时状态": datastore.get("绑定时状态"),
            },
            "live_status": live.get("status") if live else None,
            "still_bindable": bool(live and live.get("status") != DISCONNECTED),
        }

    @staticmethod
    def _to_candidate(row: dict[str, Any]) -> dict[str, Any]:
        candidate = {field: row.get(field) for field in CANDIDATE_FIELDS}
        candidate["bindable"] = row.get("status") != DISCONNECTED
        return candidate

    @staticmethod
    def _write_snapshot(datastore: dict[str, Any], candidate: dict[str, Any]) -> None:
        """绑定即固化连接身份：之后连接断开或变更，数据集仍保留原连接身份。"""
        datastore["来源连接ID"] = candidate["id"]
        datastore["来源配置编号"] = candidate.get("配置编号")
        datastore["来源连接类型"] = candidate.get("连接类型")
        datastore["来源接入地址"] = candidate.get("接入地址")
        datastore["来源负责人"] = candidate.get("负责人")
        datastore["绑定时状态"] = candidate.get("status")
        # 历史来源表名保留原值，兼容只有名称的老记录，不做覆盖。
        datastore.setdefault("来源表名", candidate.get("配置编号"))


connection_service = ConnectionService()
