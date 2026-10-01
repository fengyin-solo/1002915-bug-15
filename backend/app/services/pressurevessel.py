"""压力容器业务规则：状态流转、字段校验与筛选口径都收在这里。

审批环节按 STATUS_ORDER 一段一段往下走，每个动作只允许从它的上一环节触发；
跳着点会被拦下，并把卡住的环节原样带回给前端。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "pressurevessel"
REQUIRED_FIELDS = ["容器编号", "容器类别", "设计压力"]
OPTIONAL_FIELDS = ["工作温度", "介质名称", "容积", "安全附件"]
EDITABLE_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
# 审批环节：正常 → 超压运行 → 降压运行 → 检验中 → 已停用
STATUS_ORDER = ["正常", "超压运行", "降压运行", "检验中", "已停用"]
# 动作只允许从「上一环节」进入本环节，不允许跨环节跳转
ACTION_FLOW = {
    "超压运行": "正常",
    "降压运行": "超压运行",
    "安排检验": "降压运行",
    "办理停用": "检验中",
}
# 超压运行属于异常环节，需要在看板上计入异常量
NEGATIVE_ACTIONS = ["超压运行"]


def _sync_status(entry: dict[str, Any], status: str) -> None:
    """状态同时写入内部字段 status 与列表展示列「容器状态」，保证两处口径一致。"""
    entry["status"] = status
    entry["容器状态"] = status


class PressurevesselService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        category: str | None = None,
        design_pressure: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("容器编号", ""))]
        if category:
            rows = [row for row in rows if category in str(row.get("容器类别", ""))]
        if design_pressure:
            rows = [row for row in rows if design_pressure in str(row.get("设计压力", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        page = max(page, 1)
        size = max(size, 1)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        # 必填与选填字段都要随登记内容一起落库，选填留空时落空串而不是丢弃键
        for field in EDITABLE_FIELDS:
            entry[field] = str(values.get(field) or "").strip()
        _sync_status(entry, STATUS_ORDER[0])
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"压力容器 {entry_id} 不存在或已归档"
        merged = {field: entry.get(field, "") for field in EDITABLE_FIELDS}
        for field in EDITABLE_FIELDS:
            if field in values:
                merged[field] = str(values.get(field) or "").strip()
        missing = [field for field in REQUIRED_FIELDS if not merged[field]]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}，请补齐后再保存"
        entry.update(merged)
        return entry, ""

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"压力容器 {entry_id} 不存在或已归档"
        if action not in ACTION_FLOW:
            return None, f"动作「{action}」不属于压力容器可执行范围"
        current = str(entry.get("status") or "")
        required = ACTION_FLOW[action]
        required_index = STATUS_ORDER.index(required)
        if current != required:
            current_index = STATUS_ORDER.index(current) if current in STATUS_ORDER else -1
            if current == STATUS_ORDER[-1]:
                hint = f"当前已是「{STATUS_ORDER[-1]}」终态，审批流程已经结束"
            elif current_index >= 0 and current_index > required_index:
                hint = f"当前已到「{current}」环节，不能回头执行「{action}」"
            else:
                hint = (
                    f"当前停在「{current or '未知'}」环节，「{action}」必须先经过「{required}」；"
                    f"审批需按 {' → '.join(STATUS_ORDER)} 逐段推进，卡在「{required}」这一步"
                )
            return None, hint
        next_index = required_index + 1
        target = STATUS_ORDER[next_index]
        _sync_status(entry, target)
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"压力容器已{action}，当前环节：{target}"
