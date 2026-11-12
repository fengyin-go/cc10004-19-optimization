"""连接候选与来源绑定的端到端规则测试。

直接用 TestClient 打 ASGI 应用；store 为内存单例，每个用例前重置回种子数据。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from urllib.parse import quote

from app.main import app
from app.seed import SEED_ROWS
from app.store import store


def _headers(operator: str, role: str) -> dict[str, str]:
    # 浏览器/前端会对中文头做 percent-encode，测试保持同样口径。
    return {"X-Operator": quote(operator), "X-Operator-Role": role}


ADMIN_HEADERS = _headers("值班管理员", "admin")
MEMBER_LI_HEADERS = _headers("李涛", "member")
MEMBER_WANG_HEADERS = _headers("王珊", "member")


@pytest.fixture()
def client() -> TestClient:
    for name, rows in SEED_ROWS.items():
        store.rows(name)[:] = [dict(row) for row in rows]
    return TestClient(app)


def test_candidate_pagination_is_stable_and_without_duplicates(client: TestClient) -> None:
    seen: list[int] = []
    pages: list[list[int]] = []
    for page in (1, 2, 3):
        resp = client.get(
            "/api/connections/candidates",
            params={"page": page, "size": 2},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        payload = resp.json()
        ids = [item["id"] for item in payload["items"]]
        pages.append(ids)
        seen.extend(ids)
    assert pages == [[1, 2], [3, 4], [5, 6]]
    assert len(seen) == len(set(seen)) == 6


def test_type_and_address_combine_and_same_address_owners_split(client: TestClient) -> None:
    resp = client.get(
        "/api/connections/candidates",
        params={"conn_type": "MySQL", "address": "db.internal:3306"},
        headers=ADMIN_HEADERS,
    )
    items = resp.json()["items"]
    # 同址多负责人必须是两条独立候选；备份库（db-backup）被地址条件排除。
    assert {item["id"] for item in items} == {1, 2}
    assert {item["负责人"] for item in items} == {"张敏", "李涛"}
    assert len({item["接入地址"] for item in items}) == 1


def test_owner_locates_and_member_scope_is_limited(client: TestClient) -> None:
    resp = client.get(
        "/api/connections/candidates",
        params={"owner": "李涛"},
        headers=ADMIN_HEADERS,
    )
    items = resp.json()["items"]
    # 同负责人多地址：李涛名下两个不同地址都在，且是两条。
    assert {item["id"] for item in items} == {2, 3}

    # 普通成员不带负责人时，只能看到自己负责的连接。
    resp = client.get("/api/connections/candidates", headers=MEMBER_LI_HEADERS)
    assert {item["负责人"] for item in resp.json()["items"]} == {"李涛"}


def test_cross_scope_search_is_denied_without_count_leak(client: TestClient) -> None:
    resp = client.get(
        "/api/connections/candidates",
        params={"owner": "张敏"},
        headers=MEMBER_LI_HEADERS,
    )
    assert resp.status_code == 403
    body = resp.json()
    # 响应里不允许出现条件回显、total、items 等会暴露匹配数量的字段。
    assert set(body.keys()) == {"detail"}
    assert "张敏" not in body["detail"]
    assert "total" not in body and "items" not in body


def test_disconnected_connection_rejects_new_binding(client: TestClient) -> None:
    resp = client.post(
        "/api/connections/datastore/1/bind",
        json={"source_id": 5},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert "断开" in payload["message"]


def test_member_cannot_bind_other_owners_connection(client: TestClient) -> None:
    resp = client.post(
        "/api/connections/datastore/1/bind",
        json={"source_id": 1},
        headers=MEMBER_LI_HEADERS,  # id=1 负责人是张敏
    )
    assert resp.status_code == 403
    assert resp.json().keys() == {"detail"}


def test_binding_keeps_identity_snapshot_after_disconnect(client: TestClient) -> None:
    # 先正常绑定 id=3（已连接，李涛负责）。
    resp = client.post(
        "/api/connections/datastore/1/bind",
        json={"source_id": 3},
        headers=ADMIN_HEADERS,
    )
    assert resp.json()["ok"] is True

    # 连接随后断开。
    action = client.post(
        "/api/source/3/actions",
        json={"values": {"action": "断开连接"}},
        headers=ADMIN_HEADERS,
    )
    assert action.json()["entry"]["status"] == "已断开"

    status = client.get(
        "/api/connections/datastore/1/binding", headers=ADMIN_HEADERS
    ).json()
    assert status["bound"] is True
    assert status["live_status"] == "已断开"
    assert status["still_bindable"] is False
    # 绑定身份快照仍是断开前的连接信息。
    assert status["snapshot"]["负责人"] == "李涛"
    assert status["snapshot"]["绑定时状态"] == "已连接"


def test_legacy_name_resolves_and_conflict_requires_confirmation(client: TestClient) -> None:
    # 唯一名称：直接解析绑定。
    resp = client.post(
        "/api/connections/datastore/1/bind",
        json={"source_name": "pg.internal:5432"},
        headers=ADMIN_HEADERS,
    )
    assert resp.json()["ok"] is True
    assert resp.json()["entry"]["来源连接ID"] == 3

    # 重名：“SOUR-0001” 同时命中 SOUR-0001 与 SOUR-0001-BAK，必须 409 确认。
    resp = client.post(
        "/api/connections/datastore/2/bind",
        json={"source_name": "SOUR-0001"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert len(detail["candidates"]) == 2

    # 只带 confirmed 仍不够，必须给出具体候选 id。
    resp = client.post(
        "/api/connections/datastore/2/bind",
        json={"source_name": "SOUR-0001", "confirmed": True},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 409

    # 明确指定候选后绑定成功。
    resp = client.post(
        "/api/connections/datastore/2/bind",
        json={"source_id": 1, "confirmed": True},
        headers=ADMIN_HEADERS,
    )
    assert resp.json()["ok"] is True
    assert resp.json()["entry"]["来源连接ID"] == 1


def test_source_list_accepts_filter_bar_conditions(client: TestClient) -> None:
    # 条件栏中文字段经前端映射为后端参数：连接类型 + 接入地址组合。
    resp = client.get(
        "/api/source",
        params={"conn_type": "MySQL", "address": "db-backup"},
        headers=ADMIN_HEADERS,
    )
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["items"][0]["配置编号"] == "SOUR-0001-BAK"

    # 负责人精确定位。
    resp = client.get("/api/source", params={"owner": "王珊"}, headers=ADMIN_HEADERS)
    assert {item["负责人"] for item in resp.json()["items"]} == {"王珊"}


def test_legacy_name_with_no_match_returns_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/connections/datastore/1/bind",
        json={"source_name": "不存在的连接XYZ"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 404


def test_datastore_list_accepts_filter_bar_conditions(client: TestClient) -> None:
    resp = client.get(
        "/api/datastore",
        params={"dataset_name": "指标"},
        headers=ADMIN_HEADERS,
    )
    payload = resp.json()
    assert payload["total"] == 2

    # 来源表名条件同时命中历史名称记录与绑定后的来源配置编号。
    resp = client.get(
        "/api/datastore",
        params={"source_table": "SOUR-0005"},
        headers=ADMIN_HEADERS,
    )
    assert [item["id"] for item in resp.json()["items"]] == [3]


def test_identity_headers_support_url_encoded_chinese(client: TestClient) -> None:
    resp = client.get(
        "/api/connections/candidates",
        params={"owner": "李涛"},
        headers=_headers("李涛", "member"),
    )
    assert resp.status_code == 200
    assert {item["负责人"] for item in resp.json()["items"]} == {"李涛"}
