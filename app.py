import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =========================================================
# 월급아 어디가니? - 데모 시연용 MVP
# 핵심 시연 흐름:
# 1) 이번 달 월급 계획 생성
# 2) 계획 저장
# 3) 다음 달 시작자산 자동 계산
# 4) 월별 리포트 확인
# =========================================================

st.set_page_config(
    page_title="월급아 어디가니? MVP",
    page_icon="💸",
    layout="centered",
)

DATA_DIR = Path("data")
PROFILE_PATH = DATA_DIR / "user_profile.json"
RECORDS_PATH = DATA_DIR / "monthly_records.json"

RISK_RATIOS = {
    "안전형": 0.10,
    "안정추구형": 0.20,
    "균형형": 0.35,
    "성장추구형": 0.55,
    "적극형": 0.70,
}

CATEGORY_ORDER = ["고정지출", "생활비", "특별지출", "저축", "투자", "여유자금"]

DEFAULT_FIXED_ITEMS = [
    {"id": str(uuid4()), "name": "주거비·관리비", "amount": 0},
    {"id": str(uuid4()), "name": "통신비", "amount": 80_000},
    {"id": str(uuid4()), "name": "교통비", "amount": 50_000},
    {"id": str(uuid4()), "name": "보험료", "amount": 100_000},
]

DEFAULT_VARIABLE_ITEMS = [
    {"id": str(uuid4()), "name": "식비", "amount": 350_000},
    {"id": str(uuid4()), "name": "카페·간식", "amount": 100_000},
    {"id": str(uuid4()), "name": "모임·여가비", "amount": 150_000},
    {"id": str(uuid4()), "name": "쇼핑·생활용품", "amount": 100_000},
]

SAMPLE_RECORDS = [
    {
        "month": "2026-05",
        "income": 3_500_000,
        "fixed_total": 340_000,
        "variable_total": 760_000,
        "special_label": "가정의 달 선물",
        "special_amount": 300_000,
        "saving": 1_350_000,
        "investment": 550_000,
        "buffer": 200_000,
        "cash": 3_000_000,
        "savings_assets": 5_000_000,
        "investment_assets": 2_000_000,
        "debt": 0,
        "total_assets": 10_000_000,
        "net_assets": 10_000_000,
        "next_cash": 3_200_000,
        "next_savings_assets": 6_350_000,
        "next_investment_assets": 2_550_000,
        "next_total_assets": 12_100_000,
        "target_amount": 100_000_000,
        "goal_progress": 10.0,
        "created_at": "2026-05-31T22:00:00",
    },
    {
        "month": "2026-06",
        "income": 3_500_000,
        "fixed_total": 350_000,
        "variable_total": 820_000,
        "special_label": "여행 준비금",
        "special_amount": 500_000,
        "saving": 1_250_000,
        "investment": 400_000,
        "buffer": 180_000,
        "cash": 3_200_000,
        "savings_assets": 6_350_000,
        "investment_assets": 2_550_000,
        "debt": 0,
        "total_assets": 12_100_000,
        "net_assets": 12_100_000,
        "next_cash": 3_380_000,
        "next_savings_assets": 7_600_000,
        "next_investment_assets": 2_950_000,
        "next_total_assets": 13_930_000,
        "target_amount": 100_000_000,
        "goal_progress": 12.1,
        "created_at": "2026-06-30T22:00:00",
    },
]

st.markdown(
    """
    <style>
    .block-container {max-width: 1080px; padding-top: 1.6rem; padding-bottom: 3rem;}
    .hero {
        padding: 2.25rem 1.6rem;
        border-radius: 30px;
        background: linear-gradient(135deg, #eaf7ff 0%, #f8fbff 52%, #fff3d6 100%);
        border: 1px solid #d8edf8;
        text-align: center;
        margin-bottom: 1.1rem;
        box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
    }
    .hero h1 {font-size: 2.6rem; margin-bottom: 0.55rem; color:#101828;}
    .hero p {font-size: 1.08rem; color:#475467; line-height:1.65;}
    .card {
        border: 1px solid #e5e7eb;
        border-radius: 22px;
        padding: 1.1rem 1.15rem;
        background: #fff;
        box-shadow: 0 8px 24px rgba(15,23,42,0.04);
        min-height: 132px;
    }
    .card h4 {margin:0 0 0.35rem 0; color:#111827;}
    .muted {color:#667085; font-size:0.92rem; line-height:1.55;}
    .tiny {color:#667085; font-size:0.82rem;}
    .result-box {
        border-radius: 22px;
        padding: 1.15rem 1.25rem;
        background: #f7fbff;
        border: 1px solid #d7eaf8;
        color: #1f2937;
        margin: 0.8rem 0 1.1rem 0;
    }
    .result-box b {color:#101828;}
    .badge {
        display:inline-block;
        border-radius:999px;
        padding:0.34rem 0.72rem;
        font-size:0.84rem;
        font-weight:800;
        margin-right:0.35rem;
        margin-bottom:0.35rem;
    }
    .badge-good {background:#eafaf1; color:#027a48; border:1px solid #b7e4c7;}
    .badge-watch {background:#fff7e6; color:#b54708; border:1px solid #fedf89;}
    .badge-risk {background:#fff1f3; color:#c01048; border:1px solid #fecdd6;}
    .badge-neutral {background:#f2f4f7; color:#344054; border:1px solid #e4e7ec;}
    .plan-card {
        border:1px solid #e5e7eb;
        border-radius:20px;
        padding:1rem 1.05rem;
        background:#fff;
        margin-bottom:0.75rem;
    }
    .plan-row {
        display:flex;
        justify-content:space-between;
        gap:1rem;
        border-bottom:1px dashed #e5e7eb;
        padding:0.5rem 0;
    }
    .plan-row:last-child {border-bottom:0;}
    .plan-row span:first-child {color:#475467;}
    .plan-row span:last-child {font-weight:800; color:#101828;}
    div[data-testid="stMetric"] {
        background:#fff;
        border:1px solid #e5e7eb;
        padding:15px;
        border-radius:18px;
        box-shadow:0 8px 20px rgba(15,23,42,0.035);
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {font-weight:850; color:#101828;}
    div[data-testid="stMetric"] label {color:#667085 !important;}
    </style>
    """,
    unsafe_allow_html=True,
)


def ensure_data_dir():
    DATA_DIR.mkdir(exist_ok=True)


def won(value) -> str:
    try:
        value = float(value)
    except Exception:
        value = 0
    return f"{int(round(value)):,}원"


def pct(value) -> str:
    return f"{value:.1f}%"


def read_json(path: Path, default):
    ensure_data_dir()
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: Path, data):
    ensure_data_dir()
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_profile():
    return read_json(PROFILE_PATH, {})


def save_profile(profile):
    write_json(PROFILE_PATH, profile)


def load_records():
    records = read_json(RECORDS_PATH, [])
    return sorted(records, key=lambda x: x.get("month", ""))


def save_records(records):
    records = sorted(records, key=lambda x: x.get("month", ""))
    write_json(RECORDS_PATH, records)


def get_last_record():
    records = load_records()
    return records[-1] if records else None


def normalize_items(items, defaults):
    if not items:
        return [dict(item) for item in defaults]
    normalized = []
    for item in items:
        normalized.append({
            "id": item.get("id", str(uuid4())),
            "name": item.get("name", "항목"),
            "amount": int(item.get("amount", 0) or 0),
        })
    return normalized


def items_to_dict(items):
    output = {}
    for item in items:
        name = str(item.get("name", "")).strip() or "이름 없는 항목"
        amount = int(item.get("amount", 0) or 0)
        output[name] = output.get(name, 0) + amount
    return output


def parse_special_expense(text):
    text = (text or "").strip()
    if not text:
        return "특별지출", 0

    patterns = [
        (r"(\d+(?:\.\d+)?)\s*천만\s*원?", 10_000_000),
        (r"(\d+(?:\.\d+)?)\s*백만\s*원?", 1_000_000),
        (r"(\d+(?:\.\d+)?)\s*만\s*원?", 10_000),
        (r"(\d{1,3}(?:,\d{3})+|\d+)\s*원", 1),
    ]
    amount = 0
    for pattern, multiplier in patterns:
        match = re.search(pattern, text)
        if match:
            amount = int(float(match.group(1).replace(",", "")) * multiplier)
            break

    labels = {
        "여행": "여행비",
        "병원": "병원비",
        "의료": "의료비",
        "부모님": "가족행사",
        "생신": "가족행사",
        "자동차": "자동차 관련 비용",
        "차": "자동차 관련 비용",
        "보험": "보험료",
        "이사": "이사비",
        "경조사": "경조사",
        "결혼": "결혼/경조사",
        "전자제품": "전자제품 구매",
        "노트북": "전자제품 구매",
    }
    label = "특별지출"
    for keyword, candidate in labels.items():
        if keyword in text:
            label = candidate
            break
    return label, amount


def monthly_rate(annual_percent: float) -> float:
    return (1 + annual_percent / 100) ** (1 / 12) - 1


def build_plan(form):
    income = form["income"]
    fixed_total = sum(form["fixed_items"].values())
    variable_total = sum(form["variable_items"].values())
    cash = form["cash"]
    savings_assets = form["savings_assets"]
    investment_assets = form["investment_assets"]
    debt = form["debt"]
    target_amount = max(form["target_amount"], 1)
    target_months = max(form["target_months"], 1)
    risk = form["risk"]
    savings_rate = form["savings_rate"]
    investment_return = form["investment_return"]

    total_assets = cash + savings_assets + investment_assets
    net_assets = total_assets - debt
    available = max(income - fixed_total - variable_total, 0)

    emergency_target = max((fixed_total + variable_total) * 3, 1)
    emergency_ratio = cash / emergency_target

    investment_ratio = RISK_RATIOS.get(risk, 0.35)
    reasons = []
    if emergency_ratio < 0.5:
        investment_ratio *= 0.35
        reasons.append("비상금 위험")
    elif emergency_ratio < 1:
        investment_ratio *= 0.65
        reasons.append("비상금 보완")

    if debt > total_assets * 0.5 and debt > 0:
        investment_ratio *= 0.6
        reasons.append("부채 부담")

    if target_months <= 12:
        investment_ratio *= 0.55
        reasons.append("단기 목표")

    base_investment = int(round(available * investment_ratio))
    base_saving = int(round(available * (0.65 if emergency_ratio < 1 else 0.50)))

    if base_saving + base_investment > available * 0.92:
        scale = available * 0.92 / max(base_saving + base_investment, 1)
        base_saving = int(round(base_saving * scale))
        base_investment = int(round(base_investment * scale))

    base_buffer = max(income - fixed_total - variable_total - base_saving - base_investment, 0)

    special_label = form.get("special_label") or "특별지출"
    special_amount = int(form.get("special_amount", 0) or 0)
    special_amount = min(max(special_amount, 0), max(income - fixed_total, 0))

    current_saving = base_saving
    current_investment = base_investment
    current_buffer = base_buffer
    current_variable = variable_total
    remaining = special_amount

    use_buffer = min(current_buffer, remaining)
    current_buffer -= use_buffer
    remaining -= use_buffer

    use_investment = min(current_investment, remaining)
    current_investment -= use_investment
    remaining -= use_investment

    use_saving = min(current_saving, remaining)
    current_saving -= use_saving
    remaining -= use_saving

    # 특별지출이 너무 큰 경우 생활비까지 줄이는 경고성 계산
    variable_cut = 0
    if remaining > 0:
        variable_cut = min(current_variable, remaining)
        current_variable -= variable_cut
        remaining -= variable_cut

    saving_monthly_rate = monthly_rate(savings_rate)
    investment_monthly_rate = monthly_rate(investment_return)

    next_cash = max(cash + current_buffer, 0)
    next_savings_assets = savings_assets * (1 + saving_monthly_rate) + current_saving
    next_investment_assets = investment_assets * (1 + investment_monthly_rate) + current_investment
    next_total_assets = next_cash + next_savings_assets + next_investment_assets
    next_net_assets = next_total_assets - debt
    goal_progress = min(total_assets / target_amount * 100, 100)
    next_goal_progress = min(next_total_assets / target_amount * 100, 100)

    base_plan = {
        "고정지출": fixed_total,
        "생활비": variable_total,
        "특별지출": 0,
        "저축": base_saving,
        "투자": base_investment,
        "여유자금": base_buffer,
    }
    current_plan = {
        "고정지출": fixed_total,
        "생활비": current_variable,
        "특별지출": special_amount,
        "저축": max(current_saving, 0),
        "투자": max(current_investment, 0),
        "여유자금": max(current_buffer, 0),
    }
    next_month_plan = {
        "고정지출": fixed_total,
        "생활비": variable_total,
        "특별지출": 0,
        "저축": base_saving,
        "투자": base_investment,
        "여유자금": base_buffer,
    }

    saving_investment_rate = (base_saving + base_investment) / income * 100 if income else 0
    current_saving_investment_rate = (current_saving + current_investment) / income * 100 if income else 0

    badges = []
    if emergency_ratio >= 1:
        badges.append(("비상금 안정", "good"))
    elif emergency_ratio >= 0.5:
        badges.append(("비상금 보완", "watch"))
    else:
        badges.append(("비상금 위험", "risk"))

    if saving_investment_rate >= 45:
        badges.append(("저축·투자율 우수", "good"))
    elif saving_investment_rate >= 30:
        badges.append(("저축·투자율 적정", "neutral"))
    else:
        badges.append(("저축·투자율 낮음", "watch"))

    if special_amount > base_buffer:
        badges.append(("특별지출 조정 필요", "watch"))
    else:
        badges.append(("특별지출 감당 가능", "good"))

    if variable_cut > 0:
        badges.append(("생활비 절감 필요", "risk"))

    if special_amount > 0:
        prescription = (
            f"이번 달은 {special_label} {won(special_amount)} 때문에 평소 계획보다 저축·투자 여력이 줄어듭니다. "
            "여유자금 → 투자 → 저축 순서로 조정하고, 다음 달에는 평소 계획으로 복귀하는 것이 핵심입니다."
        )
    else:
        prescription = "이번 달 특별지출이 크지 않아 평소 저축·투자 계획을 유지하는 방향이 적절합니다."

    actions = [
        f"월급일에 저축 {won(current_plan['저축'])}과 투자 {won(current_plan['투자'])}를 먼저 분리합니다.",
        f"{special_label} 예산 {won(special_amount)}은 생활비 계좌와 분리해 추가 지출을 막습니다." if special_amount > 0 else "특별지출이 없다면 평소 계획 그대로 실행합니다.",
        f"이번 달 생활비 한도는 {won(current_plan['생활비'])}입니다. 주간 기준 약 {won(current_plan['생활비'] / 4.3)} 안에서 관리합니다.",
        f"다음 달 시작 예상 총자산은 {won(next_total_assets)}입니다. 다음 달에는 평소 저축 {won(base_saving)}, 투자 {won(base_investment)}로 복귀합니다.",
    ]

    return {
        "fixed_total": fixed_total,
        "variable_total": variable_total,
        "cash": cash,
        "savings_assets": savings_assets,
        "investment_assets": investment_assets,
        "debt": debt,
        "total_assets": total_assets,
        "net_assets": net_assets,
        "emergency_target": emergency_target,
        "emergency_ratio": emergency_ratio,
        "special_label": special_label,
        "special_amount": special_amount,
        "base_plan": base_plan,
        "current_plan": current_plan,
        "next_month_plan": next_month_plan,
        "next_cash": next_cash,
        "next_savings_assets": next_savings_assets,
        "next_investment_assets": next_investment_assets,
        "next_total_assets": next_total_assets,
        "next_net_assets": next_net_assets,
        "goal_progress": goal_progress,
        "next_goal_progress": next_goal_progress,
        "saving_investment_rate": saving_investment_rate,
        "current_saving_investment_rate": current_saving_investment_rate,
        "badges": badges,
        "reasons": reasons,
        "prescription": prescription,
        "actions": actions,
    }


def init_state():
    defaults = {
        "page": "home",
        "form_result": None,
        "form_data": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    profile = load_profile()
    if "fixed_items" not in st.session_state:
        st.session_state.fixed_items = normalize_items(profile.get("fixed_items"), DEFAULT_FIXED_ITEMS)
    if "variable_items" not in st.session_state:
        st.session_state.variable_items = normalize_items(profile.get("variable_items"), DEFAULT_VARIABLE_ITEMS)


def set_page(page):
    st.session_state.page = page
    st.rerun()


def render_badges(badges):
    html = ""
    class_map = {
        "good": "badge-good",
        "watch": "badge-watch",
        "risk": "badge-risk",
        "neutral": "badge-neutral",
    }
    for label, level in badges:
        html += f'<span class="badge {class_map.get(level, "badge-neutral")}">{label}</span>'
    st.markdown(html, unsafe_allow_html=True)


def render_plan_card(title, plan):
    rows = "".join(
        f'<div class="plan-row"><span>{k}</span><span>{won(v)}</span></div>'
        for k, v in plan.items()
    )
    st.markdown(f'<div class="plan-card"><h4>{title}</h4>{rows}</div>', unsafe_allow_html=True)


def render_item_editor(title, state_key, add_label):
    st.markdown(f"**{title}**")
    items = st.session_state[state_key]
    remove_id = None

    for idx, item in enumerate(items):
        c1, c2, c3 = st.columns([1.5, 1.2, 0.55])
        item["name"] = c1.text_input(
            "항목명",
            value=item.get("name", ""),
            key=f"{state_key}_name_{item['id']}",
            label_visibility="collapsed",
            placeholder="항목명",
        )
        item["amount"] = int(c2.number_input(
            "금액",
            min_value=0,
            value=int(item.get("amount", 0) or 0),
            step=10_000,
            format="%d",
            key=f"{state_key}_amount_{item['id']}",
            label_visibility="collapsed",
        ))
        if c3.button("삭제", key=f"remove_{state_key}_{item['id']}"):
            remove_id = item["id"]

    if remove_id:
        st.session_state[state_key] = [item for item in items if item["id"] != remove_id]
        st.rerun()

    if st.button(add_label, key=f"add_{state_key}", use_container_width=True):
        st.session_state[state_key].append({"id": str(uuid4()), "name": "새 항목", "amount": 0})
        st.rerun()


def home_page():
    st.markdown(
        """
        <div class="hero">
            <h1>💸 월급아 어디가니?</h1>
            <p><b>한 번 입력한 월급 계획을 매달 이어서 관리하세요.</b><br>
            이번 달 변화만 입력하면 다음 달 시작자산과 월별 리포트까지 자동으로 연결됩니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    records = load_records()
    last = get_last_record()

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown('<div class="card"><h4>① 이번 달 계획</h4><div class="muted">월급, 지출, 특별지출을 입력해 이번 달 배분안을 만듭니다.</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="card"><h4>② 다음 달 자동 연계</h4><div class="muted">저장된 계획을 바탕으로 다음 달 시작자산을 자동 계산합니다.</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown('<div class="card"><h4>③ 월별 리포트</h4><div class="muted">총자산, 저축·투자, 목표 달성률 추이를 확인합니다.</div></div>', unsafe_allow_html=True)

    st.write("")
    if last:
        st.success(f"마지막 저장 기록: {last['month']} · 다음 달 예상 시작 총자산 {won(last.get('next_total_assets', 0))}")
    else:
        st.info("아직 저장된 기록이 없습니다. 데모용 샘플 데이터를 넣거나, 이번 달 계획을 먼저 만들어보세요.")

    c1, c2, c3 = st.columns(3)
    if c1.button("이번 달 계획 만들기", type="primary", use_container_width=True):
        set_page("plan")
    if c2.button("월별 리포트 보기", use_container_width=True):
        set_page("report")
    if c3.button("데모 샘플 데이터 넣기", use_container_width=True):
        save_records(SAMPLE_RECORDS)
        st.success("데모 샘플 데이터가 저장되었습니다. 월별 리포트에서 바로 확인할 수 있습니다.")
        st.rerun()

    with st.expander("데모 시연 포인트"):
        st.markdown(
            """
            - 사용자는 매달 모든 자산을 다시 입력하지 않아도 됩니다.
            - 이번 달 계획을 저장하면 다음 달 시작자산이 자동 계산됩니다.
            - 월별 리포트에서 자산 추이와 목표 달성률을 확인할 수 있습니다.
            - MVP는 로컬 JSON 저장 방식이라 별도 DB 없이 바로 시연 가능합니다.
            """
        )


def get_prefill_values():
    profile = load_profile()
    last = get_last_record()

    prefill = {
        "income": int(profile.get("income", 3_500_000)),
        "cash": int(profile.get("cash", 3_000_000)),
        "savings_assets": int(profile.get("savings_assets", 5_000_000)),
        "investment_assets": int(profile.get("investment_assets", 2_000_000)),
        "debt": int(profile.get("debt", 0)),
        "target_amount": int(profile.get("target_amount", 100_000_000)),
        "target_months": int(profile.get("target_months", 36)),
        "risk": profile.get("risk", "균형형"),
        "savings_rate": float(profile.get("savings_rate", 4.0)),
        "investment_return": float(profile.get("investment_return", 6.0)),
        "goal_name": profile.get("goal_name", "목돈 마련"),
    }

    if last:
        prefill["cash"] = int(round(last.get("next_cash", prefill["cash"])))
        prefill["savings_assets"] = int(round(last.get("next_savings_assets", prefill["savings_assets"])))
        prefill["investment_assets"] = int(round(last.get("next_investment_assets", prefill["investment_assets"])))
        prefill["debt"] = int(round(last.get("debt", prefill["debt"])))
        prefill["target_amount"] = int(round(last.get("target_amount", prefill["target_amount"])))

    return prefill, last


def plan_page():
    st.title("이번 달 월급 계획 만들기")
    st.caption("저장된 기록이 있으면 다음 달 시작자산을 자동으로 불러옵니다. 바뀐 내용만 수정하세요.")

    prefill, last = get_prefill_values()
    if last:
        st.markdown(
            f"""
            <div class="result-box">
            <b>{last['month']} 기록을 불러왔어요.</b><br>
            이번 달 시작값은 지난달 예상 시작자산 기준으로 자동 채웠습니다.<br>
            현금 {won(prefill['cash'])} · 예금/적금 {won(prefill['savings_assets'])} · 투자자산 {won(prefill['investment_assets'])}
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.form("month_form"):
        with st.expander("1. 계획 월과 월급", expanded=True):
            c1, c2 = st.columns(2)
            month = c1.text_input("계획 월", value=date.today().strftime("%Y-%m"), help="예: 2026-07")
            income = c2.number_input("월 실수령액", min_value=0, value=prefill["income"], step=100_000, format="%d")

        with st.expander("2. 평소 지출 항목", expanded=True):
            st.caption("항목은 폼 밖에서 추가·삭제되고, 금액은 현재 화면에서 수정됩니다.")
            fixed_items_dict = {}
            variable_items_dict = {}

            st.markdown("**고정지출**")
            for item in st.session_state.fixed_items:
                c1, c2 = st.columns([1.5, 1.2])
                name = c1.text_input("고정지출 항목명", value=item["name"], key=f"form_fixed_name_{item['id']}", label_visibility="collapsed")
                amount = c2.number_input("고정지출 금액", min_value=0, value=int(item["amount"]), step=10_000, format="%d", key=f"form_fixed_amount_{item['id']}", label_visibility="collapsed")
                fixed_items_dict[name.strip() or "고정지출"] = int(amount)

            st.markdown("**생활비**")
            for item in st.session_state.variable_items:
                c1, c2 = st.columns([1.5, 1.2])
                name = c1.text_input("생활비 항목명", value=item["name"], key=f"form_variable_name_{item['id']}", label_visibility="collapsed")
                amount = c2.number_input("생활비 금액", min_value=0, value=int(item["amount"]), step=10_000, format="%d", key=f"form_variable_amount_{item['id']}", label_visibility="collapsed")
                variable_items_dict[name.strip() or "생활비"] = int(amount)

        with st.expander("3. 현재 자산과 목표", expanded=True):
            c1, c2 = st.columns(2)
            cash = c1.number_input("현금·입출금", min_value=0, value=prefill["cash"], step=100_000, format="%d")
            savings_assets = c2.number_input("예금·적금", min_value=0, value=prefill["savings_assets"], step=100_000, format="%d")
            investment_assets = c1.number_input("주식·ETF", min_value=0, value=prefill["investment_assets"], step=100_000, format="%d")
            debt = c2.number_input("대출 잔액", min_value=0, value=prefill["debt"], step=100_000, format="%d")
            goal_name = c1.text_input("재무 목표", value=prefill["goal_name"])
            target_amount = c2.number_input("목표 금액", min_value=1, value=prefill["target_amount"], step=1_000_000, format="%d")
            target_months = c1.number_input("목표 기간(개월)", min_value=1, value=prefill["target_months"], step=1)
            risk_index = list(RISK_RATIOS.keys()).index(prefill["risk"]) if prefill["risk"] in RISK_RATIOS else 2
            risk = c2.selectbox("투자 성향", list(RISK_RATIOS.keys()), index=risk_index)

        with st.expander("4. 수익률 가정과 이번 달 변화", expanded=True):
            c1, c2 = st.columns(2)
            savings_rate = c1.number_input("예금·적금 연 이율(%)", min_value=0.0, max_value=20.0, value=prefill["savings_rate"], step=0.1)
            investment_return = c2.number_input("투자 연평균 기대수익률(%)", min_value=-20.0, max_value=30.0, value=prefill["investment_return"], step=0.5)
            request = st.text_area(
                "이번 달만 달라진 점",
                value="이번 달은 여행비로 100만 원 정도 추가 지출이 있어. 다음 달부터는 평소 계획으로 복귀하고 싶어.",
                height=110,
            )
            parsed_label, parsed_amount = parse_special_expense(request)
            c1, c2 = st.columns(2)
            special_label = c1.text_input("특별지출 이름", value=parsed_label)
            special_amount = c2.number_input("특별지출 금액", min_value=0, value=parsed_amount, step=50_000, format="%d")

        submitted = st.form_submit_button("이번 달 계획 계산하기", type="primary", use_container_width=True)

    st.write("")
    with st.expander("지출 항목 추가·삭제"):
        c1, c2 = st.columns(2)
        with c1:
            render_item_editor("고정지출 항목 관리", "fixed_items", "+ 고정지출 항목 추가")
        with c2:
            render_item_editor("생활비 항목 관리", "variable_items", "+ 생활비 항목 추가")

    c1, c2 = st.columns(2)
    if c1.button("← 홈으로", use_container_width=True):
        set_page("home")
    if c2.button("월별 리포트 보기", use_container_width=True):
        set_page("report")

    if submitted:
        if income <= 0:
            st.error("월 실수령액을 입력해 주세요.")
            return
        if sum(fixed_items_dict.values()) + sum(variable_items_dict.values()) > income:
            st.error("평소 고정지출과 생활비 합계가 월급보다 큽니다. 입력값을 확인해 주세요.")
            return
        if not re.match(r"^\d{4}-\d{2}$", month):
            st.error("계획 월은 2026-07 형식으로 입력해 주세요.")
            return

        # 현재 폼 값을 session item에도 반영해 다음 진입 시 유지
        st.session_state.fixed_items = [
            {"id": item["id"], "name": st.session_state.get(f"form_fixed_name_{item['id']}", item["name"]), "amount": int(st.session_state.get(f"form_fixed_amount_{item['id']}", item["amount"]))}
            for item in st.session_state.fixed_items
        ]
        st.session_state.variable_items = [
            {"id": item["id"], "name": st.session_state.get(f"form_variable_name_{item['id']}", item["name"]), "amount": int(st.session_state.get(f"form_variable_amount_{item['id']}", item["amount"]))}
            for item in st.session_state.variable_items
        ]

        form_data = {
            "month": month,
            "income": int(income),
            "fixed_items": fixed_items_dict,
            "variable_items": variable_items_dict,
            "cash": int(cash),
            "savings_assets": int(savings_assets),
            "investment_assets": int(investment_assets),
            "debt": int(debt),
            "goal_name": goal_name.strip() or "재무 목표",
            "target_amount": int(target_amount),
            "target_months": int(target_months),
            "risk": risk,
            "savings_rate": float(savings_rate),
            "investment_return": float(investment_return),
            "request": request.strip(),
            "special_label": special_label.strip() or "특별지출",
            "special_amount": int(special_amount),
        }
        result = build_plan(form_data)
        st.session_state.form_data = form_data
        st.session_state.form_result = result
        st.session_state.page = "result"
        st.rerun()


def result_page():
    form = st.session_state.form_data
    result = st.session_state.form_result
    if not form or not result:
        set_page("plan")

    st.title(f"{form['month']} 월급 계획 결과")
    st.caption("이번 달은 조정 계획, 다음 달은 평소 계획으로 복귀하는 MVP 시나리오입니다.")

    render_badges(result["badges"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("이번 달 쓸 돈", won(result["fixed_total"] + result["current_plan"]["생활비"] + result["special_amount"]))
    c2.metric("이번 달 모을 돈", won(result["current_plan"]["저축"] + result["current_plan"]["투자"]))
    c3.metric("다음 달 예상 총자산", won(result["next_total_assets"]))
    c4.metric("목표 달성률", pct(result["next_goal_progress"]))

    st.markdown(
        f"""
        <div class="result-box">
        <b>이번 달 처방</b><br>
        {result['prescription']}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("목표 진행률")
    progress_value = min(result["next_goal_progress"] / 100, 1.0)
    st.progress(progress_value)
    st.caption(f"{form['goal_name']} 목표 {won(form['target_amount'])} 중 다음 달 예상 기준 {pct(result['next_goal_progress'])} 달성")

    st.subheader("이번 달 계획 vs 다음 달 복귀 계획")
    c1, c2 = st.columns(2)
    with c1:
        render_plan_card("이번 달 조정 계획", result["current_plan"])
    with c2:
        render_plan_card("다음 달 복귀 계획", result["next_month_plan"])

    st.subheader("월급 분배")
    chart_values = [result["current_plan"].get(k, 0) for k in CATEGORY_ORDER]
    fig_pie = go.Figure(data=[go.Pie(labels=CATEGORY_ORDER, values=chart_values, hole=0.58)])
    fig_pie.update_layout(margin=dict(t=20, b=20, l=20, r=20), showlegend=True)
    st.plotly_chart(fig_pie, use_container_width=True)

    st.subheader("핵심 항목 비교")
    compare_categories = ["특별지출", "저축", "투자", "여유자금"]
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        x=compare_categories,
        y=[result["base_plan"][k] for k in compare_categories],
        name="평소 계획",
    ))
    fig_bar.add_trace(go.Bar(
        x=compare_categories,
        y=[result["current_plan"][k] for k in compare_categories],
        name="이번 달 계획",
    ))
    fig_bar.update_layout(barmode="group", yaxis_title="금액(원)", margin=dict(t=20, b=20, l=20, r=20))
    st.plotly_chart(fig_bar, use_container_width=True)

    st.subheader("다음 달 시작자산 자동 계산")
    c1, c2, c3 = st.columns(3)
    c1.metric("현금", won(result["next_cash"]))
    c2.metric("예금·적금", won(result["next_savings_assets"]))
    c3.metric("투자자산", won(result["next_investment_assets"]))

    st.subheader("이번 달 실행 체크리스트")
    for action in result["actions"]:
        st.checkbox(action, value=False)

    st.warning("MVP 데모용 계산입니다. 실제 금융상품 추천이 아니라 월급 배분과 기록 연계를 보여주는 참고용입니다.")

    c1, c2, c3 = st.columns(3)
    if c1.button("계획 저장하기", type="primary", use_container_width=True):
        save_current_plan(form, result)
        st.success(f"{form['month']} 계획이 저장되었습니다. 다음 달 계획 화면에서 자동으로 이어집니다.")
    if c2.button("다음 달 계획 만들기", use_container_width=True):
        save_current_plan(form, result)
        set_page("plan")
    if c3.button("월별 리포트 보기", use_container_width=True):
        set_page("report")


def save_current_plan(form, result):
    profile = {
        "income": form["income"],
        "fixed_items": st.session_state.fixed_items,
        "variable_items": st.session_state.variable_items,
        "cash": int(round(result["next_cash"])),
        "savings_assets": int(round(result["next_savings_assets"])),
        "investment_assets": int(round(result["next_investment_assets"])),
        "debt": form["debt"],
        "goal_name": form["goal_name"],
        "target_amount": form["target_amount"],
        "target_months": form["target_months"],
        "risk": form["risk"],
        "savings_rate": form["savings_rate"],
        "investment_return": form["investment_return"],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_profile(profile)

    record = {
        "month": form["month"],
        "income": form["income"],
        "fixed_total": result["fixed_total"],
        "variable_total": result["variable_total"],
        "special_label": result["special_label"],
        "special_amount": result["special_amount"],
        "saving": result["current_plan"]["저축"],
        "investment": result["current_plan"]["투자"],
        "buffer": result["current_plan"]["여유자금"],
        "cash": result["cash"],
        "savings_assets": result["savings_assets"],
        "investment_assets": result["investment_assets"],
        "debt": result["debt"],
        "total_assets": result["total_assets"],
        "net_assets": result["net_assets"],
        "next_cash": int(round(result["next_cash"])),
        "next_savings_assets": int(round(result["next_savings_assets"])),
        "next_investment_assets": int(round(result["next_investment_assets"])),
        "next_total_assets": int(round(result["next_total_assets"])),
        "next_net_assets": int(round(result["next_net_assets"])),
        "target_amount": form["target_amount"],
        "goal_progress": result["goal_progress"],
        "next_goal_progress": result["next_goal_progress"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    records = load_records()
    records = [r for r in records if r.get("month") != form["month"]]
    records.append(record)
    save_records(records)


def report_page():
    st.title("월별 리포트")
    st.caption("저장된 월급 계획이 쌓이면 총자산과 목표 달성률 추이를 확인할 수 있습니다.")

    records = load_records()
    if not records:
        st.info("아직 저장된 월별 기록이 없습니다. 홈에서 데모 샘플 데이터를 넣거나 계획을 저장해 주세요.")
        c1, c2 = st.columns(2)
        if c1.button("데모 샘플 데이터 넣기", use_container_width=True):
            save_records(SAMPLE_RECORDS)
            st.rerun()
        if c2.button("이번 달 계획 만들기", type="primary", use_container_width=True):
            set_page("plan")
        return

    df = pd.DataFrame(records)
    df = df.sort_values("month")

    latest = records[-1]
    c1, c2, c3 = st.columns(3)
    c1.metric("최근 저장 월", latest["month"])
    c2.metric("다음 달 예상 총자산", won(latest.get("next_total_assets", 0)))
    c3.metric("목표 달성률", pct(float(latest.get("next_goal_progress", latest.get("goal_progress", 0)))))

    st.subheader("총자산 추이")
    fig_line = go.Figure()
    fig_line.add_trace(go.Scatter(
        x=df["month"],
        y=df["total_assets"],
        mode="lines+markers",
        name="월 시작 총자산",
    ))
    fig_line.add_trace(go.Scatter(
        x=df["month"],
        y=df["next_total_assets"],
        mode="lines+markers",
        name="다음 달 예상 총자산",
    ))
    fig_line.update_layout(yaxis_title="금액(원)", margin=dict(t=20, b=20, l=20, r=20))
    st.plotly_chart(fig_line, use_container_width=True)

    st.subheader("저축·투자 추이")
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(x=df["month"], y=df["saving"], name="저축"))
    fig_bar.add_trace(go.Bar(x=df["month"], y=df["investment"], name="투자"))
    fig_bar.update_layout(barmode="stack", yaxis_title="금액(원)", margin=dict(t=20, b=20, l=20, r=20))
    st.plotly_chart(fig_bar, use_container_width=True)

    st.subheader("월별 기록")
    display_df = df[[
        "month", "income", "fixed_total", "variable_total", "special_amount",
        "saving", "investment", "buffer", "total_assets", "next_total_assets", "next_goal_progress"
    ]].copy()
    display_df.columns = ["월", "월급", "고정지출", "생활비", "특별지출", "저축", "투자", "여유자금", "시작 총자산", "다음 달 예상 총자산", "목표달성률"]
    money_cols = ["월급", "고정지출", "생활비", "특별지출", "저축", "투자", "여유자금", "시작 총자산", "다음 달 예상 총자산"]
    for col in money_cols:
        display_df[col] = display_df[col].map(won)
    display_df["목표달성률"] = display_df["목표달성률"].map(lambda x: pct(float(x)))
    st.dataframe(display_df, hide_index=True, use_container_width=True)

    c1, c2, c3 = st.columns(3)
    if c1.button("이번 달 계획 만들기", type="primary", use_container_width=True):
        set_page("plan")
    if c2.button("홈으로", use_container_width=True):
        set_page("home")
    if c3.button("기록 초기화", use_container_width=True):
        save_records([])
        st.success("월별 기록을 초기화했습니다.")
        st.rerun()


def sidebar_nav():
    st.sidebar.title("💸 MVP 메뉴")
    if st.sidebar.button("홈", use_container_width=True):
        set_page("home")
    if st.sidebar.button("이번 달 계획", use_container_width=True):
        set_page("plan")
    if st.sidebar.button("월별 리포트", use_container_width=True):
        set_page("report")

    st.sidebar.divider()
    records = load_records()
    st.sidebar.caption(f"저장된 월별 기록: {len(records)}개")
    if get_last_record():
        last = get_last_record()
        st.sidebar.caption(f"최근 기록: {last['month']}")


init_state()
sidebar_nav()

if st.session_state.page == "home":
    home_page()
elif st.session_state.page == "plan":
    plan_page()
elif st.session_state.page == "result":
    result_page()
elif st.session_state.page == "report":
    report_page()
else:
    home_page()
