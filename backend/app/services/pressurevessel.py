"""压力容器业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "pressurevessel"
# 登记内容要完整落库的字段；前三个为必填，其余可留空但同样保存
ENTRY_FIELDS = ["容器编号", "容器类别", "设计压力", "工作温度", "介质名称", "容积", "安全附件", "容器状态"]
REQUIRED_FIELDS = ["容器编号", "容器类别", "设计压力"]
STATUS_ORDER = ["正常", "超压运行", "检验中", "已停用"]
TERMINAL_STATUS = "已停用"
# 审批一段一段往下走：每个动作只允许从指定前置状态发起，不允许跳步
ACTION_RULES = {
    "降压运行": {"from": ["超压运行"], "to": "正常"},
    "安排检验": {"from": ["正常"], "to": "检验中"},
    "办理停用": {"from": ["正常", "检验中"], "to": "已停用"},
}
NEGATIVE_ACTIONS = []


class PressurevesselService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("容器编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        # 登记内容完整落库，没填的字段也留位，详情和列表读到的才是同一份
        entry.update({field: values.get(field) for field in ENTRY_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"压力容器 {entry_id} 不存在或已归档"
        missing = [
            field
            for field in REQUIRED_FIELDS
            if not str(values.get(field, entry.get(field)) or "").strip()
        ]
        if missing:
            return None, f"必填字段不能为空：{'、'.join(missing)}"
        for field in ENTRY_FIELDS:
            if field in values:
                entry[field] = values[field]
        return entry, "压力容器登记内容已保存"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"压力容器 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于压力容器可执行范围"
        current = str(entry.get("status") or STATUS_ORDER[0])
        if current == TERMINAL_STATUS:
            return None, f"压力容器已停用，审批流程已结束，不能再{action}"
        rule = ACTION_RULES[action]
        if current not in rule["from"]:
            allowed = "、".join(rule["from"])
            message = f"当前状态为「{current}」，不能{action}：需处于「{allowed}」才能办理"
            if action == "办理停用" and current == "超压运行":
                message += "；超压容器请先把压力降下来（降压运行），恢复正常后再办理停用"
            return None, message
        target = rule["to"]
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"压力容器已{action}"
