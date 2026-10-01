"""压力容器模块回归测试：登记落库、逐步审批、分页完整性与错误透传。"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import SEED_ROWS
from app.store import store

client = TestClient(app)

FULL_REGISTRATION = {
    "容器编号": "PRES-1001",
    "容器类别": "第二类压力容器",
    "设计压力": "1.6MPa",
    "工作温度": "180℃",
    "介质名称": "水蒸气",
    "容积": "2m³",
    "安全附件": "安全阀、压力表",
    "容器状态": "在用",
}


@pytest.fixture(autouse=True)
def reset_pressurevessel_rows():
    """每条用例都从种子数据重新出发，避免状态流转互相污染。"""
    rows = store.rows("pressurevessel")
    rows.clear()
    rows.extend(copy.deepcopy(SEED_ROWS["pressurevessel"]))
    yield


def _action(entry_id: int, action: str) -> dict:
    response = client.post(f"/api/pressurevessel/{entry_id}/actions", json={"values": {"action": action}})
    assert response.status_code == 200
    return response.json()


def test_create_saves_every_registration_field():
    """容器类别等登记内容要跟着一起落库，详情读到的与登记的一致。"""
    response = client.post("/api/pressurevessel", json={"values": FULL_REGISTRATION})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    entry = body["entry"]
    for field, value in FULL_REGISTRATION.items():
        assert entry[field] == value, f"登记后字段 {field} 丢失"
    detail = client.get(f"/api/pressurevessel/{entry['id']}").json()
    for field, value in FULL_REGISTRATION.items():
        assert detail[field] == value, f"详情页字段 {field} 与登记内容对不上"


def test_create_allows_blank_work_temperature():
    """工作温度不是必填项，留空也要能登记、记录不能丢。"""
    values = {"容器编号": "PRES-1002", "容器类别": "第一类", "设计压力": "1.0MPa", "工作温度": ""}
    body = client.post("/api/pressurevessel", json={"values": values}).json()
    assert body["ok"] is True
    listed = client.get("/api/pressurevessel", params={"keyword": "PRES-1002"}).json()
    assert listed["total"] == 1


def test_update_design_pressure_shows_in_list():
    """改完设计压力保存之后，列表要读到新值。"""
    body = client.put("/api/pressurevessel/1", json={"values": {"设计压力": "2.5MPa"}}).json()
    assert body["ok"] is True
    listed = client.get("/api/pressurevessel").json()
    row = next(item for item in listed["items"] if item["id"] == 1)
    assert row["设计压力"] == "2.5MPa"


def test_update_rejects_blank_required_field():
    body = client.put("/api/pressurevessel/1", json={"values": {"设计压力": "  "}}).json()
    assert body["ok"] is False
    assert "设计压力" in body["message"]


def test_update_missing_entry_says_why():
    body = client.put("/api/pressurevessel/9999", json={"values": {"设计压力": "2.5MPa"}}).json()
    assert body["ok"] is False
    assert "9999" in body["message"]


def test_overpressure_must_depressurize_before_retire():
    """超压之后要先降压才能停用；跳着点当场退回并说明卡在哪一步。"""
    # 种子 id=2 处于超压运行，直接办理停用要被退回
    body = _action(2, "办理停用")
    assert body["ok"] is False
    assert "超压运行" in body["message"]
    assert "降压" in body["message"]
    # 被退回后状态不能偷跑
    assert client.get("/api/pressurevessel/2").json()["status"] == "超压运行"
    # 先降压恢复正常，再办理停用，一段一段往下走
    assert _action(2, "降压运行")["ok"] is True
    assert client.get("/api/pressurevessel/2").json()["status"] == "正常"
    assert _action(2, "办理停用")["ok"] is True
    assert client.get("/api/pressurevessel/2").json()["status"] == "已停用"


def test_step_jump_is_rejected_with_current_step():
    """正常运行的容器直接点降压运行属于跳步，要说明当前卡在哪一步。"""
    body = _action(1, "降压运行")
    assert body["ok"] is False
    assert "正常" in body["message"]
    assert "超压运行" in body["message"]
    assert client.get("/api/pressurevessel/1").json()["status"] == "正常"


def test_full_flow_goes_step_by_step():
    """正常 → 检验中 → 已停用 逐步流转；终态后任何动作都退回。"""
    assert _action(1, "安排检验")["ok"] is True
    assert client.get("/api/pressurevessel/1").json()["status"] == "检验中"
    assert _action(1, "办理停用")["ok"] is True
    assert client.get("/api/pressurevessel/1").json()["status"] == "已停用"
    body = _action(1, "安排检验")
    assert body["ok"] is False
    assert "已停用" in body["message"]


def test_pagination_keeps_every_record():
    """翻页时条数不能少：工作温度没填的记录也要一页不漏地翻出来。"""
    for index in range(25):
        values = {"容器编号": f"PRES-9{index:03d}", "容器类别": "第一类", "设计压力": "1.0MPa"}
        if index % 2 == 0:
            values["工作温度"] = "180℃"
        assert client.post("/api/pressurevessel", json={"values": values}).json()["ok"] is True
    page1 = client.get("/api/pressurevessel", params={"page": 1, "size": 20}).json()
    page2 = client.get("/api/pressurevessel", params={"page": 2, "size": 20}).json()
    assert page1["total"] == 28  # 3 条种子 + 25 条新登记
    assert len(page1["items"]) == 20
    assert len(page2["items"]) == 8
    ids = [item["id"] for item in page1["items"] + page2["items"]]
    assert len(ids) == len(set(ids)) == 28


def test_oversized_page_is_rejected_with_reason():
    """接口报错要把原因原样带出来。"""
    response = client.get("/api/pressurevessel", params={"size": 201})
    assert response.status_code == 400
    assert response.json()["detail"] == "每页最多 200 条，请缩小分页范围"
