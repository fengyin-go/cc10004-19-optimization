"""身份与授权：候选检索、来源绑定都要按当前操作者裁决。

前端通过请求头携带身份（X-Operator / X-Operator-Role），值做 URL 编码以兼容中文。
没有带头时回落到内置值班管理员，保证本地直接调接口仍可运行。
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote

from fastapi import Header, HTTPException

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLES = (ROLE_ADMIN, ROLE_MEMBER)

# 越权时统一使用固定话术，不回显条件、不透露命中数量。
FORBIDDEN_DETAIL = "无权按该负责人检索连接候选"
FORBIDDEN_BIND_DETAIL = "无权绑定该连接"

# 头部缺省身份：与前端 session store 的默认值班管理员保持一致。
DEFAULT_OPERATOR = "值班管理员"
DEFAULT_ROLE = ROLE_ADMIN


@dataclass(frozen=True)
class Operator:
    name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


def _decode_header(raw: str | None) -> str:
    """请求头可能是 percent-encoded 的中文，也可能已经是明文，两种都兼容。"""
    if not raw:
        return ""
    text = unquote(raw).strip()
    return text


def current_operator(
    x_operator: str | None = Header(default=None, alias="X-Operator"),
    x_operator_role: str | None = Header(default=None, alias="X-Operator-Role"),
) -> Operator:
    """从请求头解析当前操作者；角色非法时按普通成员处理，绝不提权。"""
    name = _decode_header(x_operator) or DEFAULT_OPERATOR
    role = _decode_header(x_operator_role) or DEFAULT_ROLE
    if role not in ROLES:
        role = ROLE_MEMBER
    return Operator(name=name, role=role)


def assert_can_search(operator: Operator, owner: str | None) -> None:
    """候选检索授权：成员只能查自己负责的连接；管理员不受限。

    越权直接 403，错误信息不含检索条件与命中数量。
    """
    if operator.is_admin:
        return
    if owner and owner != operator.name:
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)


def assert_can_bind(operator: Operator, owner: str) -> None:
    """绑定授权：只有连接负责人本人或管理员可以发起新绑定。"""
    if operator.is_admin or owner == operator.name:
        return
    raise HTTPException(status_code=403, detail=FORBIDDEN_BIND_DETAIL)
