"""演示数据注入 —— 让项目开箱即可看到完整业务闭环。

数据规模刻意覆盖 PDF 各模块的展示需求：
- 3 个项目 / 8 个站点 / 40 台充电桩（含充电枪数量、灭火器、摄像头字段）
- 5 类工单各若干（巡视/特巡/消缺/设备检查/其他），子任务严格按公式生成
- 故障记录覆盖一般/严重/危急与四种核查状态
- 巡检记录含正常与异常项、图片与 GPS
- 知识库含设备手册、SOP、故障案例
- 统计日报 + 一份历史报告
"""

from __future__ import annotations

import logging
import random
import struct
import zlib
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import UPLOAD_DIR
from app.core.enums import (
    FaultLevel,
    FaultStatus,
    SubtaskStatus,
    TimeStatus,
    WorkOrderStatus,
    WorkOrderType,
)
from app.core.utils import gen_no
from app.models import (
    AssetLedger,
    ChargingPile,
    FaultReport,
    FaultVerification,
    InspectionItem,
    InspectionRecord,
    Project,
    Station,
    User,
    WorkOrder,
    WorkOrderSubtask,
)
from app.services.work_order import build_subtask_plan, calc_subtask_count

logger = logging.getLogger("app.seed")


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def write_demo_image(rel_url: str, width: int = 320, height: int = 240) -> str:
    """按演示 URL 在 uploads 目录生成一张真实可访问的 PNG 占位图，并返回该 URL。

    种子数据往数据库写的是形如 /static/data/uploads/fault_1_1.jpg 的图片地址，
    但早期实现只写地址、不落文件，导致页面显示破图。
    这里按同一地址生成一张纯色带边框的 PNG，保证演示时图片可正常加载。

    注意：文件名沿用 .jpg（数据库里已存的地址不能改），
    但内容是 PNG 字节 —— 静态服务与浏览器按内容嗅探，仍能正常渲染。
    """
    prefix = "/static/data/uploads/"
    if not rel_url.startswith(prefix):
        return rel_url
    target = Path(UPLOAD_DIR) / rel_url[len(prefix) :]
    if target.exists():
        return rel_url
    target.parent.mkdir(parents=True, exist_ok=True)

    # 用地址做种子，让每张图颜色稳定且互不相同
    seed = zlib.crc32(rel_url.encode("utf-8"))
    bg = bytes((((seed >> 16) & 0x7F) + 96, ((seed >> 8) & 0x7F) + 96, (seed & 0x7F) + 96))

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # 每行的 filter type
        for x in range(width):
            # 四周留 6px 深色边框，便于肉眼确认图片已加载
            edge = x < 6 or y < 6 or x >= width - 6 or y >= height - 6
            raw.extend((32, 32, 32) if edge else bg)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _png_chunk(b"IEND", b"")
    )
    target.write_bytes(png)
    return rel_url

PROJECTS = [
    {"code": "PRJ-HD", "name": "华东高速服务区充电项目", "region": "江苏/浙江/上海", "owner": "华东运维中心"},
    {"code": "PRJ-HB", "name": "华北城市公交充电项目", "region": "北京/天津/河北", "owner": "华北运维中心"},
    {"code": "PRJ-HZ", "name": "华中物流园区储能项目", "region": "湖北/湖南/江西", "owner": "华中运维中心"},
]

STATIONS = [
    ("ST-HD-001", "阳澄湖服务区充电站", 0, "江苏省苏州市相城区阳澄湖服务区", 120.7231, 31.4215, "平原"),
    ("ST-HD-002", "梅村服务区充电站", 0, "江苏省无锡市新吴区梅村服务区", 120.4231, 31.5512, "平原"),
    ("ST-HD-003", "枫泾服务区充电站", 0, "上海市金山区枫泾服务区", 121.0105, 30.8871, "平原"),
    ("ST-HB-001", "大兴公交枢纽充电站", 1, "北京市大兴区黄村镇公交枢纽", 116.3389, 39.7285, "平原"),
    ("ST-HB-002", "武清城际充电站", 1, "天津市武清区城际站停车场", 117.0561, 39.3831, "平原"),
    ("ST-HB-003", "正定机场充电站", 1, "河北省石家庄市正定机场停车楼", 114.6963, 38.2808, "平原"),
    ("ST-HZ-001", "东西湖物流园充电站", 2, "湖北省武汉市东西湖区物流园", 114.1372, 30.6218, "平原"),
    ("ST-HZ-002", "岳阳城陵矶港充电站", 2, "湖南省岳阳市城陵矶新港区", 113.1526, 29.4402, "丘陵"),
]

PILE_MODELS = [
    ("DC-120KW", 120.0, 2, "直流双枪"),
    ("DC-180KW", 180.0, 2, "直流双枪"),
    ("DC-240KW", 240.0, 4, "直流四枪"),
    ("AC-7KW", 7.0, 1, "交流单枪"),
    ("AC-21KW", 21.0, 1, "交流单枪"),
]

MANUFACTURERS = ["特来电", "星星充电", "国家电网", "云快充", "科士达"]

FAULT_TYPES = [
    "充电枪故障",
    "通信故障",
    "计费异常",
    "功率模块故障",
    "急停按钮异常",
    "绝缘监测报警",
    "屏幕显示异常",
    "刷卡模块故障",
]

FAULT_DESCRIPTIONS = {
    "充电枪故障": "枪头插入后无法启动充电，枪头触点有明显烧蚀痕迹，充电枪指示灯常亮红灯。",
    "通信故障": "充电桩离线，平台无法下发指令，现场 4G 信号强度偏低，网关口指示灯异常。",
    "计费异常": "充电结束后平台账单金额与桩端显示不一致，疑似电表通信异常导致计费偏差。",
    "功率模块故障": "充电功率无法达到额定值，仅能维持 30kW，桩体报功率模块故障码 E05，散热风扇声音异常。",
    "急停按钮异常": "急停按钮被按下后未复位，充电桩无法启动，急停回路指示异常。",
    "绝缘监测报警": "雨后桩体报绝缘监测报警，绝缘电阻低于阈值，桩体底部有轻微积水。",
    "屏幕显示异常": "触摸屏花屏，部分菜单无法点击，重启后仍存在。",
    "刷卡模块故障": "刷卡无反应，读卡器指示灯不亮，扫码充电功能正常。",
}

KNOWLEDGE_DOCS = [
    {
        "title": "充电桩日常巡检作业指导书（SOP）",
        "category": "SOP",
        "content": """一、巡检准备
携带万用表、绝缘电阻测试仪、红外测温仪、绝缘手套、验电笔、清洁工具，确认工单信息与站点清单。
二、外观与环境检查
1. 检查桩体外观有无破损、变形、锈蚀，柜门锁具是否完好。
2. 检查站台清洁情况，无杂物堆积，排水通畅无积水。
3. 检查标识标牌、警示标识是否清晰完整。
三、电气安全检查
1. 测试急停按钮功能，按下后应在 1 秒内切断输出，复位后恢复正常。
2. 检查接地线连接可靠，接地电阻不大于 4 欧姆。
3. 检查输入输出线缆无破损、无过热变色痕迹，接线端子无松动。
4. 检查配电箱无异响、无异味、无放电痕迹。
四、充电功能检查
1. 检查充电枪头无烧蚀、无变形，卡扣动作正常，电子锁可靠。
2. 实车或假负载测试刷卡/扫码启动，确认启动成功率。
3. 对比桩端显示功率与平台数据，偏差不应超过 5%。
五、消防设施检查
1. 灭火器在有效期内，压力表指针在绿色区域；无灭火器配置的站点应登记为「无」。
2. 烟感、温感装置工作正常，无遮挡。
六、监控与通信检查
1. 摄像头画面清晰，角度覆盖充电区域，录像可回放。
2. 通信模块在线，平台无离线告警，心跳正常。
七、异常处置
发现异常项应现场拍照留证并在工单中勾选「异常」，填写不超过 200 字的备注说明现象；
涉及起火、冒烟、漏电、绝缘失效等高危现象时立即停止充电、设置警戒并上报，按危急故障处理。""",
        "tags": ["巡检", "SOP", "安全"],
    },
    {
        "title": "直流充电桩功率模块故障诊断与处置手册",
        "category": "设备手册",
        "content": """适用机型：DC-120KW / DC-180KW / DC-240KW 系列直流充电桩。
一、故障现象
充电功率无法达到额定值、桩体报 E05/E06 故障码、充电中途停机、模块散热风扇异响。
二、可能根因
1. 功率模块内部 IGBT 损坏或驱动电路异常。
2. 散热风扇失效或滤网堵塞导致模块过温降额。
3. 交流接触器触点氧化导致接触不良，输入电压偏低。
4. 电网三相电压不平衡或电压跌落。
5. 模块通信线松动，主控无法获取模块状态。
三、诊断步骤
1. 读取桩体故障码与模块运行日志，记录降额发生时间点。
2. 用红外测温仪测量模块进出风口温差，进风口滤网压差。
3. 检查散热风扇转速，清理或更换滤网。
4. 测量三相输入电压与接触器触点温升，触点温升超过 40K 应更换接触器。
5. 检查模块通信排线，重新插拔并观察是否恢复。
四、处置措施
1. 更换故障功率模块，更换后需做满载测试。
2. 清理滤网或更换散热风扇。
3. 更换交流接触器。
4. 电压异常属电网侧问题，联系供电部门并做记录。
五、预防建议
每季度清理滤网一次；夏季高温前专项检查散热系统；建立模块更换台账跟踪寿命。""",
        "tags": ["功率模块", "故障诊断", "直流桩"],
    },
    {
        "title": "充电桩绝缘监测报警（绝缘故障）应急处置规程",
        "category": "故障案例",
        "content": """一、风险等级
绝缘故障涉及人身安全，雨雪天气发生后按「危急」等级处理，SLA 4 小时内响应。
二、现场处置顺序
1. 立即停止该桩充电服务，在平台将该桩置为停用状态，现场设置警戒围栏与警示牌。
2. 断开桩体上级断路器，验电确认无电后挂牌上锁。
3. 用绝缘电阻测试仪测量直流输出正负极对地绝缘电阻，低于 1 兆欧判定为绝缘不合格。
4. 检查桩体密封条、电缆进出线口、底部排水孔是否进水受潮。
5. 检查充电枪线绝缘层有无破损、老化、被碾压痕迹。
6. 检查接地系统连续性，接地电阻应不大于 4 欧姆。
三、处置措施
1. 桩体进水：断电除湿，更换密封件，做淋雨试验后复测绝缘。
2. 枪线破损：更换充电枪线总成，不得采用缠绕胶带的临时处理。
3. 接地不良：整改接地极与接地扁铁，复测合格后恢复送电。
四、恢复送电条件
绝缘电阻大于 1 兆欧、接地电阻小于 4 欧姆、无渗水痕迹、空载测试正常，四项同时满足。
五、归档要求
保留检测数据、照片与处置记录，纳入设备健康档案，同一桩体 3 个月内重复发生应升级为专项整改。""",
        "tags": ["绝缘", "安全", "应急处置"],
    },
    {
        "title": "充电桩通信故障排查指引（4G/以太网）",
        "category": "故障案例",
        "content": """一、故障现象
平台显示充电桩离线、指令下发失败、订单无法上传、桩体显示通信异常。
二、排查顺序（由简到繁）
1. 检查桩体供电是否正常，通信模块指示灯状态（常亮/闪烁/熄灭）。
2. 测试现场 4G 信号强度，RSRP 低于 -105dBm 判定为信号弱。
3. 检查天线连接是否松动、天线是否被金属遮挡。
4. 以太网接入场景：检查网线水晶头是否氧化、交换机端口是否正常。
5. 检查平台侧证书是否过期、接入地址与端口是否变更。
6. 检查网关固件版本，确认是否存在已知缺陷。
三、处置措施
1. 信号弱：更换高增益天线或调整安装位置，必要时加装信号放大器。
2. 网线问题：重做水晶头或更换网线，测试连通性。
3. 证书过期：更新平台证书并重启网关。
4. 固件缺陷：升级到最新稳定版本，升级前备份配置。
四、验证
恢复后观察平台在线状态持续 30 分钟，手动下发一次远程启动指令确认通道正常。
五、预防
每季度巡检通信模块与天线状态；建立离线时长统计，单站月离线超过 2 小时启动专项排查。""",
        "tags": ["通信", "4G", "离线"],
    },
    {
        "title": "灭火器与消防设施检查标准（含「无」配置说明）",
        "category": "SOP",
        "content": """一、配置要求
充电站应按每 4 台充电桩不少于 1 具 4kg 干粉灭火器配置，储能舱应单独配置。
部分室内站点或依托建筑消防系统的站点可能未单独配置灭火器，台账中灭火器类型应登记为「无」。
二、检查内容
1. 灭火器类型与规格是否与台账一致（干粉/二氧化碳/水基/洁净气体）。
2. 压力表指针是否在绿色区域，瓶体有无锈蚀、变形、磕碰。
3. 喷管有无老化开裂，保险销与铅封是否完好。
4. 生产日期与检验日期是否在有效期内（干粉灭火器出厂 5 年首次检验，之后每 2 年一次）。
5. 放置位置是否易于取用，是否被杂物遮挡。
三、动态表单要求
台账维护时，灭火器类型选择「无」后，规格与生产日期字段应自动隐藏且不参与必填校验；
选择其他类型时，需按单瓶录入规格与生产日期。
四、异常处理
压力不足、超期未检、瓶体锈蚀的灭火器应立即更换，并在工单中记录更换数量与编号。""",
        "tags": ["消防", "灭火器", "台账"],
    },
    {
        "title": "充电桩计费异常核查与退费流程",
        "category": "SOP",
        "content": """一、适用场景
用户投诉扣费金额异常、平台账单与桩端显示不一致、离线订单未上传导致漏计费。
二、核查步骤
1. 调取该订单的桩端原始记录与平台结算报文，比对起止时间、电量、单价、金额。
2. 检查电表通信是否正常，读取电表当前读数与平台记录读数。
3. 检查费率模板配置是否与当前电价政策一致，是否存在跨费率时段切换错误。
4. 检查桩体本地时钟是否漂移，漂移超过 1 分钟应校时。
5. 检查离线订单补传机制是否生效。
三、处置措施
1. 电表通信异常：修复通信链路，重新抄读电表。
2. 费率错误：修正费率模板并重算受影响订单。
3. 时钟漂移：校时并检查 NTP 服务。
4. 确属多扣费用：按流程提交退费申请，附核查记录。
四、时限要求
计费类投诉应在 24 小时内给出初步核查结论，72 小时内完成闭环。
五、预防
每月核对一次费率模板与电价政策；每季度做一次电表与平台数据一致性抽查。""",
        "tags": ["计费", "退费", "投诉"],
    },
]


async def backdate_records(db: AsyncSession) -> None:
    """把演示记录的时间戳回填到其业务发生日期（PDF 3.9 趋势图 / 3.12 报告环比需要）。

    否则所有记录 created_at 相同，统计日报与趋势全部为 0。
    """
    from sqlalchemy import text

    today = date.today()
    floor_dt = f"{(today - timedelta(days=40)).isoformat()} 08:00:00"

    # 工单：created_at 对齐巡检开始日期（偏移量的选取保证落在统计窗口内）
    await db.execute(
        text(
            """
            UPDATE work_order
               SET created_at = CASE
                     WHEN inspect_start_date IS NOT NULL
                       THEN datetime(inspect_start_date, '8 hours')
                     ELSE :floor
                   END
             WHERE created_at >= :floor
            """
        ),
        {"floor": floor_dt},
    )

    # 巡检记录：对齐子任务计划日期
    await db.execute(
        text(
            """
            UPDATE inspection_record
               SET created_at = COALESCE(
                     (SELECT datetime(st.plan_date, '10 hours')
                        FROM work_order_subtask st
                       WHERE st.id = inspection_record.subtask_id),
                     :floor)
             WHERE created_at >= :floor
            """
        ),
        {"floor": floor_dt},
    )

    # 故障：按上报时间或发生时间
    await db.execute(
        text(
            """
            UPDATE fault_report
               SET created_at = CASE
                     WHEN reported_at IS NOT NULL THEN reported_at
                     WHEN occurred_at IS NOT NULL THEN occurred_at
                     ELSE :floor
                   END
             WHERE created_at >= :floor
            """
        ),
        {"floor": floor_dt},
    )

    await db.commit()


async def seed_demo_data(db: AsyncSession) -> bool:
    """注入演示数据；已有业务数据时跳过。返回是否执行了注入。"""
    existing_projects = int(
        (await db.execute(select(func.count(Project.id)))).scalar() or 0
    )
    if existing_projects > 0:
        return False

    random.seed(20260101)
    today = date.today()

    # ---------------- 项目 ----------------
    projects: list[Project] = []
    for item in PROJECTS:
        project = Project(**item, status=True)
        db.add(project)
        projects.append(project)
    await db.flush()

    # ---------------- 站点 ----------------
    stations: list[Station] = []
    for idx, (code, name, pidx, address, lng, lat, terrain) in enumerate(STATIONS):
        # PDF 3.10 二期：灭火器含「无」选项；摄像头球机/枪机数量
        no_extinguisher = idx % 5 == 4
        station = Station(
            code=code,
            name=name,
            project_id=projects[pidx].id,
            address=address,
            longitude=lng,
            latitude=lat,
            terrain=terrain,
            extinguisher_type="无" if no_extinguisher else random.choice(["干粉", "二氧化碳", "水基"]),
            extinguisher_spec=None if no_extinguisher else random.choice(["4kg", "5kg", "3kg"]),
            extinguisher_produced_at=None
            if no_extinguisher
            else datetime.combine(today - timedelta(days=random.randint(90, 1200)), time()),
            dome_camera_count=random.randint(1, 4),
            bullet_camera_count=random.randint(0, 6),
            camera_password=f"Hik{random.randint(100000, 999999)}",
            contact_name=random.choice(["王强", "刘敏", "陈涛", "赵磊", "周欣"]),
            contact_phone=f"139{random.randint(10000000, 99999999)}",
            status=True,
        )
        db.add(station)
        stations.append(station)
    await db.flush()

    # ---------------- 充电桩 ----------------
    piles: list[ChargingPile] = []
    seq = 0
    for station in stations:
        pile_count = random.randint(4, 6)
        for _ in range(pile_count):
            seq += 1
            model, power, guns, gun_types = random.choice(PILE_MODELS)
            online = random.random() > 0.08
            status = "运行" if online else random.choice(["离线", "故障", "停用"])
            pile = ChargingPile(
                asset_code=f"CP{station.code.split('-')[-1]}{seq:04d}",
                name=f"{station.name}-{seq:02d}号桩",
                station_id=station.id,
                model=model,
                rated_power=power,
                gun_count=guns,
                gun_types=gun_types,
                manufacturer=random.choice(MANUFACTURERS),
                install_date=datetime.combine(
                    today - timedelta(days=random.randint(200, 1500)), time()
                ),
                warranty_until=datetime.combine(
                    today + timedelta(days=random.randint(-100, 900)), time()
                ),
                status=status,
                online=online,
            )
            db.add(pile)
            piles.append(pile)
    await db.flush()

    # ---------------- 运维人员（用于工单分配） ----------------
    # 首次启动时用户表为空，这里先创建内置账号（含运维人员）与排班，
    # 否则工单、巡检等依赖人员的数据无法生成。
    from app.bootstrap import ensure_users

    await ensure_users(db)

    staff = (
        await db.execute(select(User).where(User.user_type == "staff"))
    ).scalars().all()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalars().first()
    staff_pool = list(staff) or ([admin] if admin else [])
    if not staff_pool:
        logger.warning("缺少可用执行人，跳过工单/巡检演示数据")
        await db.commit()
        return True

    piles_by_station: dict[str, list[ChargingPile]] = {}
    for pile in piles:
        piles_by_station.setdefault(pile.station_id or "", []).append(pile)

    # ---------------- 工单 + 子任务（严格按公式） ----------------
    order_specs = [
        # (类型, 站点切片, 周期, 频率, 次数, 起始偏移天, 结束偏移天, 状态)
        # 偏移量使 created_at 落在 T-20 ~ T-3，恰好铺满统计日报的 30 天窗口
        (WorkOrderType.PATROL.value, [0, 1], 1, "月", 1, -6, 12, WorkOrderStatus.COMPLETED.value),
        (WorkOrderType.PATROL.value, [2, 3], 1, "周", 1, -17, 3, WorkOrderStatus.PENDING_DONE.value),
        (WorkOrderType.EQUIPMENT.value, [1, 4], 1, "月", 1, -12, 14, WorkOrderStatus.PENDING_ACCEPT.value),
        (WorkOrderType.SPECIAL.value, [0, 2, 5], 1, "月", 2, -15, 9, WorkOrderStatus.PENDING_DONE.value),
        (WorkOrderType.DEFECT.value, [3], 1, "月", 1, -13, 5, WorkOrderStatus.COMPLETED.value),
        (WorkOrderType.DEFECT.value, [6], 1, "月", 1, -4, 10, WorkOrderStatus.PENDING_ACCEPT.value),
        (WorkOrderType.OTHER.value, [7], 1, "月", 1, -20, 11, WorkOrderStatus.RETURNED.value),
        (WorkOrderType.PATROL.value, [4, 5], 1, "日", 1, -7, 18, WorkOrderStatus.PENDING_DONE.value),
        (WorkOrderType.PATROL.value, [0], 1, "月", 1, -14, -8, WorkOrderStatus.COMPLETED.value),
        (WorkOrderType.DEFECT.value, [1], 1, "月", 1, -18, -11, WorkOrderStatus.COMPLETED.value),
        (WorkOrderType.EQUIPMENT.value, [2, 6], 1, "周", 1, -16, 2, WorkOrderStatus.COMPLETED.value),
        (WorkOrderType.PATROL.value, [3, 7], 1, "月", 1, -19, 4, WorkOrderStatus.PENDING_DONE.value),
        (WorkOrderType.OTHER.value, [4], 1, "月", 1, -9, 7, WorkOrderStatus.COMPLETED.value),
        (WorkOrderType.SPECIAL.value, [6, 7], 1, "月", 3, -11, 6, WorkOrderStatus.COMPLETED.value),
    ]

    work_orders: list[WorkOrder] = []
    for i, (otype, idxs, cycle, freq, count, s_off, e_off, status) in enumerate(order_specs, 1):
        chosen = [stations[j] for j in idxs if j < len(stations)]
        if not chosen:
            continue
        start = today + timedelta(days=s_off)
        end = today + timedelta(days=e_off)
        inspector = staff_pool[i % len(staff_pool)]
        total = calc_subtask_count(otype, len(chosen), cycle, freq, count)

        order = WorkOrder(
            order_no=f"WO{(today - timedelta(days=abs(s_off))).strftime('%Y%m%d')}{i:04d}",
            order_name=f"{chosen[0].name}等{len(chosen)}站{otype}工单",
            order_type=otype,
            project_id=chosen[0].project_id,
            station_id=chosen[0].id if len(chosen) == 1 else None,
            station_name="、".join(s.name for s in chosen[:3]),
            station_address=chosen[0].address if len(chosen) == 1 else None,
            station_ids=[s.id for s in chosen],
            station_names=[s.name for s in chosen],
            status=status,
            time_status=TimeStatus.NORMAL.value,
            inspector_id=inspector.id,
            inspector_name=inspector.real_name,
            inspect_start_date=start,
            inspect_end_date=end,
            inspect_frequency=freq,
            inspect_count=count,
            inspect_cycle=cycle,
            subtask_total=total,
            remark=f"演示数据：{otype}工单，子任务按「{'站点数量 × 巡检周期 × 巡检频率' if otype not in ('消缺', '特巡') else ('固定 1 个子任务' if otype == '消缺' else '站点数量 × 巡检次数')}」生成",
            source="手工",
            created_by=admin.id if admin else None,
            reject_reason="现场人员不足，申请延后执行" if status == WorkOrderStatus.RETURNED.value else None,
            accepted_at=datetime.now() - timedelta(days=max(1, abs(s_off) - 1))
            if status != WorkOrderStatus.PENDING_ACCEPT.value
            else None,
            completed_at=datetime.now() - timedelta(days=2)
            if status == WorkOrderStatus.COMPLETED.value
            else None,
        )
        db.add(order)
        await db.flush()

        plan = build_subtask_plan(
            order_type=otype,
            stations=chosen,
            inspect_start=start,
            inspect_end=end,
            inspect_cycle=cycle,
            inspect_frequency=freq,
            inspect_count=count,
            assignee=inspector,
            piles_by_station=piles_by_station,
        )
        subtask_rows: list[WorkOrderSubtask] = []
        for item in plan:
            # 按工单状态决定子任务完成程度
            if status == WorkOrderStatus.COMPLETED.value:
                st_status = SubtaskStatus.COMPLETED.value
            elif status == WorkOrderStatus.PENDING_DONE.value:
                st_status = (
                    SubtaskStatus.COMPLETED.value
                    if item["sequence"] % 2 == 1
                    else SubtaskStatus.PENDING.value
                )
            else:
                st_status = SubtaskStatus.PENDING.value

            subtask = WorkOrderSubtask(
                work_order_id=order.id,
                order_no=order.order_no,
                order_name=order.order_name,
                order_type=otype,
                station_id=item["station_id"],
                station_name=item["station_name"],
                pile_id=item["pile_id"],
                pile_asset_code=item["pile_asset_code"],
                sequence=item["sequence"],
                plan_date=item["plan_date"],
                plan_time_window=item["plan_time_window"],
                status=st_status,
                assignee_id=inspector.id,
                assignee_name=inspector.real_name,
                route_order=item["route_order"],
                completed_at=datetime.now() - timedelta(days=random.randint(1, 20))
                if st_status == SubtaskStatus.COMPLETED.value
                else None,
            )
            db.add(subtask)
            subtask_rows.append(subtask)
        await db.flush()

        order.subtask_done = sum(
            1 for s in subtask_rows if s.status == SubtaskStatus.COMPLETED.value
        )
        work_orders.append(order)

        # ---------------- 巡检记录（仅已完成子任务） ----------------
        from app.services.inspection import template_for

        template = template_for(otype)
        for subtask in subtask_rows:
            if subtask.status != SubtaskStatus.COMPLETED.value:
                continue
            items = []
            abnormal_hit = random.random() < 0.28
            abnormal_index = random.randint(0, len(template) - 1) if abnormal_hit else -1
            for ti, tpl in enumerate(template):
                is_abnormal = ti == abnormal_index
                items.append(
                    {
                        "item_name": tpl["name"],
                        "item_group": tpl["group"],
                        "result": "异常" if is_abnormal else "正常",
                        "remark": (
                            random.choice(
                                [
                                    "枪头触点有轻微烧蚀，建议下次巡检重点复查",
                                    "桩体底部有积水痕迹，排水孔需清理",
                                    "通信模块指示灯异常闪烁",
                                    "接地线连接螺栓有松动迹象",
                                ]
                            )
                            if is_abnormal
                            else ""
                        ),
                        "images": [
                            write_demo_image(f"/static/data/uploads/demo_{subtask.sequence}_{k}.jpg")
                            for k in range(1, random.randint(2, 4))
                        ],
                    }
                )
            normal = sum(1 for x in items if x["result"] == "正常")
            abnormal = sum(1 for x in items if x["result"] == "异常")
            checkin = datetime.combine(
                subtask.plan_date or today, time(hour=random.randint(8, 10))
            )

            record = InspectionRecord(
                subtask_id=subtask.id,
                work_order_id=order.id,
                inspector_id=inspector.id,
                inspector_name=inspector.real_name,
                station_id=subtask.station_id,
                station_name=subtask.station_name,
                checkin_location=chosen[0].address if chosen else None,
                checkin_lng=chosen[0].longitude if chosen else None,
                checkin_lat=chosen[0].latitude if chosen else None,
                checkin_time=checkin,
                checkout_location=chosen[0].address if chosen else None,
                checkout_lng=chosen[0].longitude if chosen else None,
                checkout_lat=chosen[0].latitude if chosen else None,
                checkout_time=checkin + timedelta(hours=2),
                content={
                    "order_type": otype,
                    "items": items,
                    "station_name": subtask.station_name,
                    "pile_asset_code": subtask.pile_asset_code,
                },
                images=[
                    write_demo_image(f"/static/data/uploads/demo_{subtask.sequence}_{k}.jpg")
                    for k in range(1, 4)
                ],
                abnormal_count=abnormal,
                normal_count=normal,
                remark="现场巡检完成，异常项已拍照留证。" if abnormal else "现场巡检正常。",
                status="已完成",
            )
            db.add(record)
            await db.flush()

            for item in items:
                db.add(
                    InspectionItem(
                        inspection_id=record.id,
                        work_order_id=order.id,
                        pile_id=subtask.pile_id,
                        pile_asset_code=subtask.pile_asset_code,
                        item_name=item["item_name"],
                        item_group=item["item_group"],
                        result=item["result"],
                        remark=item["remark"][:200],
                        images=item["images"],
                    )
                )
            subtask.item_summary = f"正常 {normal} 项 / 异常 {abnormal} 项"

    # ---------------- 故障记录 ----------------
    fault_specs = [
        (FaultLevel.CRITICAL.value, FaultStatus.PENDING_VERIFY.value, -1),
        (FaultLevel.SERIOUS.value, FaultStatus.PENDING_VERIFY.value, -2),
        (FaultLevel.GENERAL.value, FaultStatus.VERIFIED.value, -6),
        (FaultLevel.SERIOUS.value, FaultStatus.VERIFIED.value, -12),
        (FaultLevel.GENERAL.value, FaultStatus.REJECTED.value, -8),
        (FaultLevel.GENERAL.value, FaultStatus.VERIFIED.value, -17),
        (FaultLevel.SERIOUS.value, FaultStatus.PENDING_REPORT.value, 0),
        (FaultLevel.GENERAL.value, FaultStatus.VERIFIED.value, -14),
        (FaultLevel.GENERAL.value, FaultStatus.VERIFIED.value, -4),
        (FaultLevel.SERIOUS.value, FaultStatus.VERIFIED.value, -19),
        (FaultLevel.GENERAL.value, FaultStatus.VERIFIED.value, -10),
    ]
    for i, (level, status, day_off) in enumerate(fault_specs, 1):
        station = stations[i % len(stations)]
        station_piles = piles_by_station.get(station.id, [])
        pile = station_piles[i % len(station_piles)] if station_piles else None
        ftype = FAULT_TYPES[i % len(FAULT_TYPES)]
        reporter = staff_pool[i % len(staff_pool)]
        occurred = datetime.combine(today + timedelta(days=day_off), time(hour=random.randint(8, 18)))

        fault = FaultReport(
            fault_no=f"FT{(today + timedelta(days=day_off)).strftime('%Y%m%d')}{i:04d}",
            project_id=station.project_id,
            station_id=station.id,
            station_name=station.name,
            pile_id=pile.id if pile else None,
            pile_asset_code=pile.asset_code if pile else None,
            reporter_id=reporter.id,
            reporter_name=reporter.real_name,
            reporter_phone=reporter.phone,
            fault_type=ftype,
            fault_level=level,
            description=FAULT_DESCRIPTIONS.get(ftype),
            images=[
                write_demo_image(f"/static/data/uploads/fault_{i}_{k}.jpg") for k in range(1, 3)
            ],
            status=status,
            is_draft=status == FaultStatus.PENDING_REPORT.value,
            occurred_at=occurred,
            reported_at=None if status == FaultStatus.PENDING_REPORT.value else occurred + timedelta(hours=1),
        )
        db.add(fault)
        await db.flush()

        if status in (FaultStatus.VERIFIED.value, FaultStatus.REJECTED.value):
            db.add(
                FaultVerification(
                    fault_id=fault.id,
                    verifier_id=admin.id if admin else None,
                    verifier_name=admin.real_name if admin else "系统",
                    verify_status=status,
                    verify_level=level,
                    verify_desc=(
                        f"现场核查确认：{FAULT_DESCRIPTIONS.get(ftype, '')[:60]}… "
                        "已按规程处置，复测数据恢复正常范围。"
                        if status == FaultStatus.VERIFIED.value
                        else "现场核查未复现故障现象，判定为误报，已驳回并建议持续观察。"
                    ),
                    images=[
                        write_demo_image(f"/static/data/uploads/verify_{i}_{k}.jpg")
                        for k in range(1, 3)
                    ],
                    need_defect_order=status == FaultStatus.VERIFIED.value and level != FaultLevel.GENERAL.value,
                )
            )

    await db.commit()

    # ---------------- 回填历史时间戳 ----------------
    # 演示数据在同一时刻写入，若不回填 created_at，统计日报与趋势图将全部为 0。
    # 按业务发生日期回填，使统计与报告具备真实的趋势与环比。
    await backdate_records(db)

    # ---------------- 台账同步 ----------------
    from app.services.asset import sync_ledger

    await sync_ledger(db)

    # ---------------- 知识库 ----------------
    from app.ai.knowledge import upsert_document

    for doc in KNOWLEDGE_DOCS:
        await upsert_document(
            db,
            title=doc["title"],
            category=doc["category"],
            content=doc["content"],
            tags=doc["tags"],
            source_type="text",
        )

    # ---------------- 统计日报（近 30 天） ----------------
    from app.services.statistics import build_daily_statistics

    for offset in range(30, 0, -1):
        await build_daily_statistics(db, today - timedelta(days=offset))

    # ---------------- 历史报告（一份日报告） ----------------
    try:
        from app.ai.report_service import generate_report

        await generate_report(db, report_type="daily", use_llm=False)
    except Exception as exc:  # pragma: no cover
        logger.warning("生成演示报告失败：%s", exc)

    logger.info(
        "演示数据注入完成：项目 %s，站点 %s，充电桩 %s，工单 %s，故障 %s，知识库 %s",
        len(projects),
        len(stations),
        len(piles),
        len(work_orders),
        len(fault_specs),
        len(KNOWLEDGE_DOCS),
    )
    return True
