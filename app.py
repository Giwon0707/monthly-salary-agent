import json
import os
import re
from uuid import uuid4

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


st.set_page_config(
    page_title="월급아 어디가니?",
    page_icon="💸",
    layout="centered",
)

st.markdown(
    """
    <style>
    .block-container {max-width: 1040px; padding-top: 2rem; padding-bottom: 3rem;}
    .hero {
        padding: 2.3rem 1.6rem;
        border-radius: 28px;
        background: linear-gradient(135deg, #eaf7ff 0%, #f7fbff 48%, #fff4dc 100%);
        border: 1px solid #d8edf8;
        text-align: center;
        margin-bottom: 1.2rem;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
    }
    .hero h1 {font-size: 2.55rem; margin-bottom: 0.55rem; color:#101828;}
    .hero p {font-size: 1.08rem; color: #425466; line-height:1.65;}
    .info-card {
        border: 1px solid #e5e7eb;
        border-radius: 20px;
        padding: 1.05rem 1.1rem;
        background: white;
        color: #1f2937;
        min-height: 124px;
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.035);
    }
    .info-card h4 {margin: 0 0 0.35rem 0; color: #111827;}
    .muted {color: #667085; font-size: 0.92rem; line-height:1.55;}
    .tiny {color: #667085; font-size: 0.84rem;}

    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        padding: 15px;
        border-radius: 18px;
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.035);
    }
    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] {color: #667085 !important;}
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {color: #111827 !important; font-weight: 800;}

    .result-box {
        border-radius: 20px;
        padding: 1.15rem 1.25rem;
        background: #f7fbff;
        border: 1px solid #d7eaf8;
        color: #1f2937;
        margin: 0.8rem 0 1.1rem 0;
    }
    .result-box b {color: #111827;}
    .summary-card {
        border-radius: 22px;
        padding: 1.1rem 1.15rem;
        background: #ffffff;
        border: 1px solid #e5e7eb;
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.035);
        min-height: 132px;
    }
    .summary-card .label {color:#667085; font-size:0.88rem; margin-bottom:0.35rem;}
    .summary-card .value {font-size:1.45rem; font-weight:800; color:#101828; margin-bottom:0.35rem;}
    .summary-card .desc {color:#667085; font-size:0.88rem; line-height:1.45;}
    .badge {
        display: inline-block;
        border-radius: 999px;
        padding: 0.34rem 0.72rem;
        font-size: 0.84rem;
        font-weight: 700;
        margin-right: 0.35rem;
        margin-bottom: 0.35rem;
    }
    .badge-good {background:#eafaf1; color:#027a48; border:1px solid #b7e4c7;}
    .badge-watch {background:#fff7e6; color:#b54708; border:1px solid #fedf89;}
    .badge-risk {background:#fff1f3; color:#c01048; border:1px solid #fecdd6;}
    .badge-neutral {background:#f2f4f7; color:#344054; border:1px solid #e4e7ec;}
    .plan-card {
        border: 1px solid #e5e7eb;
        border-radius: 20px;
        padding: 1rem 1.05rem;
        background: #ffffff;
        margin-bottom: 0.75rem;
    }
    .plan-row {
        display: flex;
        justify-content: space-between;
        gap: 1rem;
        border-bottom: 1px dashed #e5e7eb;
        padding: 0.48rem 0;
    }
    .plan-row:last-child {border-bottom: 0;}
    .plan-row span:first-child {color:#475467;}
    .plan-row span:last-child {font-weight:750; color:#101828;}
    .delta-plus {color:#c01048; font-weight:800;}
    .delta-minus {color:#175cd3; font-weight:800;}
    .delta-zero {color:#667085; font-weight:800;}
    .section-spacer {height: 0.6rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

RISK_RATIOS = {
    "안전형": 0.10,
    "안정추구형": 0.20,
    "균형형": 0.35,
    "성장추구형": 0.55,
    "적극형": 0.70,
}

CATEGORY_ORDER = ["고정지출", "생활비", "특별지출", "저축", "투자", "여유자금"]
CHART_COLORS = ["#4E79A7", "#F28E2B", "#E15759", "#59A14F", "#B07AA1", "#9C755F"]
MONEY_UNIT = 1_000
NON_LIVING_ADJUSTMENT_ITEMS = {"여유자금", "투자", "저축"}


def round_money(value: float, unit: int = MONEY_UNIT) -> int:
    return int(round(float(value) / unit) * unit)


def floor_money(value: float, unit: int = MONEY_UNIT) -> int:
    return int(float(value) // unit * unit)


def ceil_money(value: float, unit: int = MONEY_UNIT) -> int:
    value = float(value)
    return int(-(-value // unit) * unit)


def won(value: float) -> str:
    return f"{round_money(value):,}원"


def pct(value: float) -> str:
    return f"{value:.1f}%"


def new_item(name: str, amount: int) -> dict:
    return {"id": uuid4().hex[:8], "name": name, "amount": int(amount)}


def default_fixed_items() -> list[dict]:
    return [
        new_item("주거비·관리비", 0),
        new_item("통신비", 80_000),
        new_item("교통비", 50_000),
        new_item("보험료", 100_000),
        new_item("구독료", 30_000),
        new_item("기타 고정지출", 40_000),
    ]


def default_variable_items() -> list[dict]:
    return [
        new_item("식비", 350_000),
        new_item("카페·간식", 100_000),
        new_item("모임·여가비", 150_000),
        new_item("쇼핑·생활용품", 100_000),
        new_item("기타 생활비", 0),
    ]


def init_state():
    defaults = {
        "page": "home",
        "result": None,
        "form_data": None,
        "fixed_items_state": default_fixed_items(),
        "variable_items_state": default_variable_items(),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def monthly_rate(annual_percent: float) -> float:
    annual_decimal = annual_percent / 100
    return (1 + annual_decimal) ** (1 / 12) - 1


def extract_special_expense(text: str) -> tuple[str, int]:
    text = text.strip()
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
        "부모님": "부모님 생신/가족행사",
        "생신": "부모님 생신/가족행사",
        "여행": "여행",
        "보험": "보험료",
        "병원": "병원비",
        "의료": "의료비",
        "이사": "이사비",
        "자동차": "자동차 관련 비용",
        "경조사": "경조사",
        "결혼": "결혼/경조사",
        "전자제품": "전자제품 구매",
        "예약금": "예약금",
    }

    label = "특별지출"
    for keyword, value in labels.items():
        if keyword in text:
            label = value
            break

    return label, round_money(amount)


def ask_ai_for_context(form: dict) -> dict | None:
    api_key = None
    try:
        api_key = st.secrets.get("OPENAI_API_KEY")
    except Exception:
        api_key = os.getenv("OPENAI_API_KEY")

    if not api_key or OpenAI is None:
        return None

    model = "gpt-4.1-mini"
    try:
        model = st.secrets.get("OPENAI_MODEL", model)
    except Exception:
        model = os.getenv("OPENAI_MODEL", model)

    prompt = f"""
사용자의 이번 달 재무 요청을 분석해 JSON만 반환하세요.

사용자 요청: {form['request']}

반환 형식:
{{
  "special_event": "이번 달에만 발생하는 특별 상황 또는 없음",
  "special_amount": 숫자,
  "priority": "이번 달 조정에서 가장 중요한 기준 한 문장"
}}

규칙:
- 특별 상황은 평소 계획이 아니라 이번 달에만 적용되는 일시적 변화로 해석
- 금액은 원 단위 숫자
- 명시된 금액이 없으면 0
- 특정 금융상품이나 종목은 추천하지 않음
"""
    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": "당신은 사용자의 평소 재무계획과 이번 달의 일시적 변화를 구분하는 분석 도우미입니다. JSON만 반환하세요.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw = response.output_text.strip()
        raw = re.sub(r"^```json\s*|\s*```$", "", raw)
        return json.loads(raw)
    except Exception:
        return None


def sum_items(items: list[dict]) -> int:
    return int(sum(max(int(item.get("amount", 0)), 0) for item in items))


def get_item_amount(items: list[dict], keywords: list[str], fallback: float = 0) -> float:
    for item in items:
        name = item.get("name", "")
        if any(keyword in name for keyword in keywords):
            return float(item.get("amount", 0))
    return fallback


def build_base_plan(
    income: int,
    fixed_total: int,
    variable_total: int,
    cash: int,
    debt: int,
    total_assets: int,
    target_months: int,
    risk: str,
) -> tuple[dict, float, list[str]]:
    available = max(income - fixed_total - variable_total, 0)
    emergency_target = max((fixed_total + variable_total) * 3, 1)
    emergency_ratio = cash / emergency_target

    investment_ratio = RISK_RATIOS[risk]
    reasons = []

    if emergency_ratio < 0.5:
        investment_ratio *= 0.35
        reasons.append("비상금 부족")
    elif emergency_ratio < 1:
        investment_ratio *= 0.65
        reasons.append("비상금 보완 필요")

    if debt > total_assets * 0.5 and debt > 0:
        investment_ratio *= 0.6
        reasons.append("부채 부담")

    if target_months <= 12:
        investment_ratio *= 0.55
        reasons.append("단기 목표")

    investment = round_money(available * investment_ratio)

    if emergency_ratio < 1:
        saving = round_money(available * 0.65)
    else:
        saving = round_money(available * 0.50)

    if saving + investment > available * 0.92:
        scale = available * 0.92 / max(saving + investment, 1)
        saving = floor_money(saving * scale)
        investment = floor_money(investment * scale)

    # 모든 월별 실행 금액은 1,000원 단위로 맞춘다.
    available_rounded = floor_money(available)
    while saving + investment > available_rounded:
        if investment >= MONEY_UNIT:
            investment -= MONEY_UNIT
        elif saving >= MONEY_UNIT:
            saving -= MONEY_UNIT
        else:
            break

    buffer_money = max(available_rounded - saving - investment, 0)

    plan = {
        "고정지출": fixed_total,
        "생활비": variable_total,
        "특별지출": 0,
        "저축": max(saving, 0),
        "투자": max(investment, 0),
        "여유자금": max(buffer_money, 0),
    }

    return plan, emergency_ratio, reasons


def adjust_for_special(
    base_plan: dict,
    special_amount: int,
    variable_items: list[dict] | None = None,
    reduction_rules: list[dict] | None = None,
) -> tuple[dict, list[dict], list[dict], int]:
    """
    이번 달 특별지출을 반영한다.
    조정 순서: 여유자금 → 사용자가 체크한 생활비 항목 → 투자 → 저축.
    고정지출은 건드리지 않고, 생활비는 사용자가 허용한 항목과 한도 안에서만 먼저 줄인다.
    """
    plan = {key: round_money(value) for key, value in dict(base_plan).items()}
    special_amount = max(round_money(special_amount), 0)
    plan["특별지출"] = special_amount

    current_variable_items = [dict(item) for item in (variable_items or [])]
    reductions: list[dict] = []
    remaining = special_amount

    use_buffer = min(plan["여유자금"], remaining)
    plan["여유자금"] -= use_buffer
    remaining -= use_buffer
    if use_buffer > 0:
        reductions.append({
            "항목": "여유자금",
            "조정액": use_buffer,
            "이유": "가장 먼저 사용하는 완충 금액",
        })

    rules = sorted(reduction_rules or [], key=lambda x: int(x.get("priority", 99)))
    item_by_id = {item.get("id"): item for item in current_variable_items}
    for rule in rules:
        if remaining <= 0:
            break
        item = item_by_id.get(rule.get("id"))
        if not item:
            continue
        original_amount = round_money(item.get("amount", 0))
        floor_amount = max(round_money(rule.get("floor_amount", 0)), 0)
        floor_amount = min(floor_amount, original_amount)
        max_cut = max(original_amount - floor_amount, 0)
        cut = min(max_cut, remaining)
        cut = floor_money(cut)
        if cut <= 0:
            continue
        item["amount"] = original_amount - cut
        plan["생활비"] = max(plan["생활비"] - cut, 0)
        remaining -= cut
        reductions.append({
            "항목": item.get("name", "생활비"),
            "조정액": cut,
            "이유": f"최소 유지금액 {won(floor_amount)} 기준",
        })

    use_investment = min(plan["투자"], remaining)
    plan["투자"] -= use_investment
    remaining -= use_investment
    if use_investment > 0:
        reductions.append({
            "항목": "투자",
            "조정액": use_investment,
            "이유": "이번 달만 일시적으로 축소하고 다음 달 계획에서 다시 설정",
        })

    use_saving = min(plan["저축"], remaining)
    plan["저축"] -= use_saving
    remaining -= use_saving
    if use_saving > 0:
        reductions.append({
            "항목": "저축",
            "조정액": use_saving,
            "이유": "마지막으로 줄이는 핵심 목표 금액",
        })

    return plan, current_variable_items, reductions, remaining


def project_with_one_time_adjustment(
    target_months: int,
    cash: float,
    savings_assets: float,
    investment_assets: float,
    current_plan: dict,
    base_plan: dict,
    savings_rate: float,
    investment_return: float,
) -> tuple[float, list[dict]]:
    saving_balance = float(savings_assets)
    investment_balance = float(investment_assets)
    cash_balance = float(cash)

    saving_monthly_rate = monthly_rate(savings_rate)
    investment_monthly_rate = monthly_rate(investment_return)

    history = [{"개월": 0, "총자산": cash_balance + saving_balance + investment_balance}]

    for month in range(1, target_months + 1):
        monthly_saving = current_plan["저축"] if month == 1 else base_plan["저축"]
        monthly_investment = current_plan["투자"] if month == 1 else base_plan["투자"]

        saving_balance = saving_balance * (1 + saving_monthly_rate) + monthly_saving
        investment_balance = investment_balance * (1 + investment_monthly_rate) + monthly_investment

        history.append({"개월": month, "총자산": cash_balance + saving_balance + investment_balance})

    return history[-1]["총자산"], history


def months_to_target_with_one_time_adjustment(
    target_amount: float,
    cash: float,
    savings_assets: float,
    investment_assets: float,
    current_plan: dict,
    base_plan: dict,
    savings_rate: float,
    investment_return: float,
    max_months: int = 600,
) -> int:
    current_total = cash + savings_assets + investment_assets
    if current_total >= target_amount:
        return 0

    saving_balance = float(savings_assets)
    investment_balance = float(investment_assets)
    saving_monthly_rate = monthly_rate(savings_rate)
    investment_monthly_rate = monthly_rate(investment_return)

    for month in range(1, max_months + 1):
        monthly_saving = current_plan["저축"] if month == 1 else base_plan["저축"]
        monthly_investment = current_plan["투자"] if month == 1 else base_plan["투자"]

        saving_balance = saving_balance * (1 + saving_monthly_rate) + monthly_saving
        investment_balance = investment_balance * (1 + investment_monthly_rate) + monthly_investment

        if cash + saving_balance + investment_balance >= target_amount:
            return month

    return -1


def make_diagnosis(result_seed: dict, income: int) -> tuple[str, str, list[dict]]:
    badges = []
    emergency_ratio = result_seed["emergency_ratio"]
    special_amount = result_seed["special_amount"]
    base_plan = result_seed["base_plan"]
    current_plan = result_seed["current_plan"]
    target_shortfall = result_seed["target_shortfall"]
    saving_investment_rate = result_seed["saving_investment_rate"]

    if emergency_ratio < 0.5:
        badges.append({"label": "비상금 위험", "type": "risk"})
    elif emergency_ratio < 1:
        badges.append({"label": "비상금 보완", "type": "watch"})
    else:
        badges.append({"label": "비상금 안정", "type": "good"})

    if special_amount > base_plan["여유자금"] and special_amount > 0:
        badges.append({"label": "특별지출 조정 필요", "type": "watch"})
    elif special_amount > 0:
        badges.append({"label": "특별지출 대응 가능", "type": "good"})

    if saving_investment_rate >= 45:
        badges.append({"label": "저축·투자율 우수", "type": "good"})
    elif saving_investment_rate >= 30:
        badges.append({"label": "저축·투자율 적정", "type": "neutral"})
    else:
        badges.append({"label": "저축·투자율 낮음", "type": "watch"})

    if target_shortfall > 0:
        badges.append({"label": "목표 부족액 있음", "type": "watch"})
    else:
        badges.append({"label": "목표권 진입", "type": "good"})

    if any(badge["type"] == "risk" for badge in badges):
        status = "위험"
        summary = "투자 확대보다 비상금 확보와 고정지출 안정화가 우선입니다."
    elif any(badge["type"] == "watch" for badge in badges):
        status = "조정 필요"
        if current_plan["투자"] < base_plan["투자"]:
            summary = "이번 달은 투자금을 줄이고 저축과 필수 지출을 우선하는 방식이 적절합니다."
        else:
            summary = "이번 달 계획은 실행 가능하지만 특별지출이 반복되면 평소 계획을 다시 잡아야 합니다."
    else:
        status = "안정"
        summary = "현재 계획은 안정적으로 실행 가능한 편이며, 다음 달 계획 기준만 잘 지키면 됩니다."

    return status, summary, badges


def calculate_plan(form: dict) -> dict:
    income = form["income"]
    cash = form["cash"]
    savings_assets = form["savings_assets"]
    investment_assets = form["investment_assets"]
    debt = form["debt"]
    target_amount = form["target_amount"]
    target_months = max(form["target_months"], 1)
    risk = form["risk"]
    savings_rate = form["savings_rate"]
    investment_return = form["investment_return"]

    fixed_total = sum_items(form["fixed_items"])
    variable_total = sum_items(form["variable_items"])

    total_assets = cash + savings_assets + investment_assets
    net_assets = total_assets - debt

    base_plan, emergency_ratio, adjustment_reasons = build_base_plan(
        income=income,
        fixed_total=fixed_total,
        variable_total=variable_total,
        cash=cash,
        debt=debt,
        total_assets=total_assets,
        target_months=target_months,
        risk=risk,
    )

    ai_context = ask_ai_for_context(form)
    fallback_label, fallback_amount = extract_special_expense(form["request"])

    if ai_context:
        special_label = ai_context.get("special_event") or fallback_label
        special_amount = round_money(ai_context.get("special_amount") or fallback_amount or 0)
        priority = ai_context.get("priority") or "이번 달의 일시적인 지출만 조정하고 평소 계획은 유지합니다."
    else:
        special_label = fallback_label
        special_amount = fallback_amount
        priority = "여유자금과 조정 가능한 생활비를 먼저 활용하고, 부족한 부분만 투자·저축에서 조정합니다."

    special_amount = min(max(round_money(special_amount), 0), floor_money(max(income - fixed_total, 0)))
    current_plan, current_variable_items, variable_reductions, uncovered_amount = adjust_for_special(
        base_plan=base_plan,
        special_amount=special_amount,
        variable_items=form["variable_items"],
        reduction_rules=form.get("reduction_rules", []),
    )

    projected_at_target, projection_history = project_with_one_time_adjustment(
        target_months=target_months,
        cash=cash,
        savings_assets=savings_assets,
        investment_assets=investment_assets,
        current_plan=current_plan,
        base_plan=base_plan,
        savings_rate=savings_rate,
        investment_return=investment_return,
    )

    expected_months = months_to_target_with_one_time_adjustment(
        target_amount=target_amount,
        cash=cash,
        savings_assets=savings_assets,
        investment_assets=investment_assets,
        current_plan=current_plan,
        base_plan=base_plan,
        savings_rate=savings_rate,
        investment_return=investment_return,
    )

    base_monthly_contribution = base_plan["저축"] + base_plan["투자"]
    current_monthly_contribution = current_plan["저축"] + current_plan["투자"]
    one_time_reduction = base_monthly_contribution - current_monthly_contribution

    comparison_rows = []
    for category in CATEGORY_ORDER:
        base_value = base_plan[category]
        current_value = current_plan[category]
        comparison_rows.append({
            "항목": category,
            "평소 계획": base_value,
            "이번 달 계획": current_value,
            "증감": current_value - base_value,
        })

    principal_at_target = (
        total_assets
        + current_plan["저축"]
        + current_plan["투자"]
        + max(target_months - 1, 0) * (base_plan["저축"] + base_plan["투자"])
    )
    expected_profit = projected_at_target - principal_at_target
    target_shortfall = max(target_amount - projected_at_target, 0)

    saving_investment_rate = base_monthly_contribution / income * 100 if income > 0 else 0
    if saving_investment_rate >= 60:
        plan_intensity = "매우 높음"
    elif saving_investment_rate >= 45:
        plan_intensity = "높음"
    elif saving_investment_rate >= 30:
        plan_intensity = "보통"
    else:
        plan_intensity = "낮음"

    weekly_food = get_item_amount(form["variable_items"], ["식비", "식", "밥"], variable_total * 0.45) / 4.3
    weekly_social = get_item_amount(form["variable_items"], ["모임", "여가", "데이트"], variable_total * 0.2) / 4.3
    emergency_target = (fixed_total + variable_total) * 3

    result_seed = {
        "emergency_ratio": emergency_ratio,
        "special_amount": special_amount,
        "base_plan": base_plan,
        "current_plan": current_plan,
        "target_shortfall": target_shortfall,
        "saving_investment_rate": saving_investment_rate,
    }
    status, diagnosis_summary, badges = make_diagnosis(result_seed, income)

    actions = [
        f"월급일에 이번 달 저축 {won(current_plan['저축'])}과 투자 {won(current_plan['투자'])}를 먼저 분리",
        f"{special_label} 비용 {won(special_amount)}은 생활비 계좌와 분리" if special_amount > 0 else "이번 달 특별지출이 없으므로 평소 계획 그대로 실행",
        f"식비는 주당 약 {won(weekly_food)}, 모임·여가비는 주당 약 {won(weekly_social)} 안에서 관리",
        f"다음 달 계획은 저축 {won(base_plan['저축'])}, 투자 {won(base_plan['투자'])} 기준으로 설정",
        f"월말에 비상금이 권장치 {won(emergency_target)} 대비 {emergency_ratio * 100:.0f}% 이상인지 확인",
    ]

    explanation = (
        f"평소에는 매월 저축 {won(base_plan['저축'])}, 투자 {won(base_plan['투자'])}를 유지하는 계획입니다. "
        f"이번 달에는 {special_label} {won(special_amount)}이 발생해 여유자금·체크한 생활비·투자·저축 순으로 조정했습니다. "
        f"다음 달부터는 다시 평소 계획을 적용한다고 가정했습니다."
    )

    return {
        "total_assets": total_assets,
        "net_assets": net_assets,
        "fixed_total": fixed_total,
        "variable_total": variable_total,
        "emergency_ratio": emergency_ratio,
        "emergency_target": emergency_target,
        "special_label": special_label,
        "special_amount": special_amount,
        "priority": priority,
        "base_plan": base_plan,
        "current_plan": current_plan,
        "comparison_rows": comparison_rows,
        "base_monthly_contribution": base_monthly_contribution,
        "current_monthly_contribution": current_monthly_contribution,
        "one_time_reduction": one_time_reduction,
        "projected_at_target": projected_at_target,
        "principal_at_target": principal_at_target,
        "expected_profit": expected_profit,
        "target_shortfall": target_shortfall,
        "saving_investment_rate": saving_investment_rate,
        "plan_intensity": plan_intensity,
        "projection_history": projection_history,
        "expected_months": expected_months,
        "explanation": explanation,
        "actions": actions,
        "adjustment_reasons": adjustment_reasons,
        "current_variable_items": current_variable_items,
        "variable_reductions": variable_reductions,
        "uncovered_amount": uncovered_amount,
        "ai_used": ai_context is not None,
        "status": status,
        "diagnosis_summary": diagnosis_summary,
        "badges": badges,
    }


def render_money_card(label: str, value: str, desc: str = ""):
    st.markdown(
        f"""
        <div class="summary-card">
            <div class="label">{label}</div>
            <div class="value">{value}</div>
            <div class="desc">{desc}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_plan_card(title: str, plan: dict):
    rows = "".join(
        f"<div class='plan-row'><span>{category}</span><span>{won(plan[category])}</span></div>"
        for category in CATEGORY_ORDER
        if plan.get(category, 0) > 0 or category in ["저축", "투자", "여유자금"]
    )
    st.markdown(f"<div class='plan-card'><b>{title}</b><br><br>{rows}</div>", unsafe_allow_html=True)


def render_badges(badges: list[dict]):
    class_map = {
        "good": "badge-good",
        "watch": "badge-watch",
        "risk": "badge-risk",
        "neutral": "badge-neutral",
    }
    html = "".join(
        f"<span class='badge {class_map.get(badge['type'], 'badge-neutral')}'>{badge['label']}</span>"
        for badge in badges
    )
    st.markdown(html, unsafe_allow_html=True)


def render_item_editor(state_key: str, title: str, add_label: str):
    st.markdown(f"**{title}**")
    items = st.session_state[state_key]

    for idx, item in enumerate(list(items)):
        cols = st.columns([1.35, 1.15, 0.45])
        name_key = f"{state_key}_{item['id']}_name"
        amount_key = f"{state_key}_{item['id']}_amount"

        item["name"] = cols[0].text_input(
            "항목명",
            value=item.get("name", ""),
            key=name_key,
            label_visibility="collapsed",
            placeholder="예: 자동차 할부",
        ).strip()
        item["amount"] = int(cols[1].number_input(
            "금액",
            min_value=0,
            value=int(item.get("amount", 0)),
            step=MONEY_UNIT,
            format="%d",
            key=amount_key,
            label_visibility="collapsed",
        ))
        if cols[2].button("삭제", key=f"delete_{state_key}_{item['id']}"):
            st.session_state[state_key] = [x for x in items if x["id"] != item["id"]]
            st.rerun()

    if st.button(add_label, key=f"add_{state_key}", use_container_width=True):
        st.session_state[state_key].append(new_item("새 항목", 0))
        st.rerun()

    total = sum_items(st.session_state[state_key])
    st.caption(f"{title} 합계: {won(total)}")
    return st.session_state[state_key]


def home():
    st.markdown(
        """
        <div class="hero">
            <h1>💸 월급아 어디가니?</h1>
            <p><b>이번 달은 흔들려도, 계획은 무너지지 않게.</b><br>
            평소 월급 계획과 일시 지출을 분리해 이번 달 실행안을 만들어 드립니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            '<div class="info-card"><h4>✍️ 항목 직접 편집</h4><div class="muted">고정지출과 생활비 항목을 직접 추가·삭제할 수 있습니다.</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            '<div class="info-card"><h4>🎯 개인 맞춤형 조정</h4><div class="muted">이번 달 특이사항과 줄일 수 있는 생활비 항목을 반영해 계획을 조정합니다.</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            '<div class="info-card"><h4>📊 한눈에 보는 결과</h4><div class="muted">이번 달 쓸 돈, 모을 돈, 목표 달성률을 카드형으로 보여줍니다.</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    if st.button("내 월급 계획 만들기", type="primary", use_container_width=True):
        st.session_state.page = "form"
        st.rerun()

    st.caption("입력 정보는 현재 세션에서만 사용되며 별도로 저장하지 않습니다.")


def default_floor_amount_for_item(name: str, amount: int) -> int:
    """
    사용자가 특별지출이 있어도 최소한 유지하고 싶은 생활비 하한 금액.
    퍼센트 조정보다 실제 돈 관리 감각에 가까운 방식이다.
    """
    if amount <= 0:
        return 0
    if any(keyword in name for keyword in ["카페", "간식"]):
        ratio = 0.50
    elif any(keyword in name for keyword in ["모임", "여가", "데이트"]):
        ratio = 0.60
    elif any(keyword in name for keyword in ["쇼핑", "생활용품"]):
        ratio = 0.55
    elif any(keyword in name for keyword in ["식비", "식", "밥"]):
        return min(amount, 250_000)
    else:
        ratio = 0.70
    return round_money(amount * ratio)


def default_priority_for_item(name: str) -> int:
    if any(keyword in name for keyword in ["카페", "간식"]):
        return 1
    if any(keyword in name for keyword in ["모임", "여가", "데이트"]):
        return 2
    if any(keyword in name for keyword in ["쇼핑", "생활용품"]):
        return 3
    if any(keyword in name for keyword in ["식비", "식", "밥"]):
        return 4
    return 5


def default_check_for_item(name: str) -> bool:
    return any(keyword in name for keyword in ["식비", "식", "밥", "카페", "간식", "모임", "여가", "데이트", "쇼핑", "생활용품"])


def render_reduction_rules(variable_items: list[dict]) -> list[dict]:
    st.markdown("**이번 달 줄일 수 있는 생활비 항목**")
    st.caption("특별지출이 생겼을 때 먼저 줄여도 되는 항목을 체크하고, 각 항목의 최소 유지금액을 정하세요. 고정지출은 조정하지 않습니다.")

    rules: list[dict] = []
    adjustable_items = [item for item in variable_items if int(item.get("amount", 0)) > 0 and item.get("name")]
    if not adjustable_items:
        st.info("금액이 입력된 생활비 항목이 있으면 조정 우선순위를 설정할 수 있습니다.")
        return rules

    for item in adjustable_items:
        item_id = item["id"]
        name = item.get("name", "생활비")
        amount = int(item.get("amount", 0))
        cols = st.columns([1.5, 1.15, 0.9])
        checked = cols[0].checkbox(
            f"{name} 줄이기 허용",
            value=default_check_for_item(name),
            key=f"cut_enable_{item_id}",
        )
        floor_amount = cols[1].number_input(
            "최소 유지금액",
            min_value=0,
            max_value=amount,
            value=default_floor_amount_for_item(name, amount),
            step=MONEY_UNIT,
            format="%d",
            key=f"floor_amount_{item_id}",
            disabled=not checked,
        )
        priority = cols[2].number_input(
            "우선순위",
            min_value=1,
            max_value=10,
            value=default_priority_for_item(name),
            step=1,
            key=f"cut_priority_{item_id}",
            disabled=not checked,
        )
        if checked and floor_amount < amount:
            rules.append({
                "id": item_id,
                "name": name,
                "amount": amount,
                "floor_amount": int(floor_amount),
                "priority": int(priority),
            })

    return rules


def input_form():
    st.title("내 월급 계획 만들기")
    st.caption("필수 정보는 간단히, 세부 지출은 원하는 만큼 직접 추가·삭제하세요.")

    with st.expander("1. 월급과 목표", expanded=True):
        c1, c2 = st.columns(2)
        income = c1.number_input("월 실수령액", min_value=0, value=3_500_000, step=MONEY_UNIT, format="%d")
        goal_name = c2.text_input("재무 목표", value="목돈 마련")
        target_amount = c1.number_input("목표 금액", min_value=0, value=100_000_000, step=MONEY_UNIT, format="%d")
        target_months = c2.number_input("목표 기간(개월)", min_value=1, value=36, step=1)

    with st.expander("2. 평소 지출 항목", expanded=True):
        st.caption("항목명과 금액을 직접 수정하고, 필요 없는 항목은 삭제하세요.")
        fixed_items = render_item_editor("fixed_items_state", "고정지출", "+ 고정지출 항목 추가")
        st.divider()
        variable_items = render_item_editor("variable_items_state", "생활비", "+ 생활비 항목 추가")
        st.divider()
        reduction_rules = render_reduction_rules(variable_items)

    with st.expander("3. 현재 자산과 수익률 가정", expanded=False):
        c1, c2 = st.columns(2)
        cash = c1.number_input("현금·입출금 통장", min_value=0, value=3_000_000, step=MONEY_UNIT, format="%d")
        savings_assets = c2.number_input("예금·적금", min_value=0, value=5_000_000, step=MONEY_UNIT, format="%d")
        investment_assets = c1.number_input("주식·ETF", min_value=0, value=2_000_000, step=MONEY_UNIT, format="%d")
        debt = c2.number_input("대출 잔액", min_value=0, value=0, step=MONEY_UNIT, format="%d")
        savings_rate = c1.number_input("예금·적금 연 이율(%)", min_value=0.0, max_value=20.0, value=4.0, step=0.1)
        investment_return = c2.number_input("투자 연평균 기대수익률(%)", min_value=-20.0, max_value=30.0, value=6.0, step=0.5)
        risk = c2.selectbox("투자 성향", list(RISK_RATIOS.keys()), index=4)

    with st.expander("4. 이번 달 특이사항", expanded=True):
        request = st.text_area(
            "이번 달 상황이나 원하는 조정 내용을 적어주세요.",
            value="이번 달은 해외여행으로 100만 원 정도 추가 지출이 있을 것 같아.",
            height=120,
            help="예: 다음 달 여행 예약금으로 이번 달 30만 원이 더 필요해.",
        )

    fixed_total = sum_items(fixed_items)
    variable_total = sum_items(variable_items)
    remaining = income - fixed_total - variable_total

    st.markdown("### 입력 요약")
    c1, c2, c3 = st.columns(3)
    c1.metric("평소 고정지출", won(fixed_total))
    c2.metric("평소 생활비", won(variable_total))
    c3.metric("계획 가능 금액", won(remaining))

    if remaining < 0:
        st.error("평소 고정지출과 생활비 합계가 월급보다 큽니다. 항목 금액을 조정해 주세요.")

    submitted = st.button("이번 달 계획하기", type="primary", use_container_width=True)

    c1, c2 = st.columns(2)
    if c1.button("← 시작화면으로", use_container_width=True):
        st.session_state.page = "home"
        st.rerun()
    if c2.button("기본 항목으로 초기화", use_container_width=True):
        st.session_state.fixed_items_state = default_fixed_items()
        st.session_state.variable_items_state = default_variable_items()
        st.rerun()

    if submitted:
        cleaned_fixed = [item for item in fixed_items if item.get("name") and int(item.get("amount", 0)) >= 0]
        cleaned_variable = [item for item in variable_items if item.get("name") and int(item.get("amount", 0)) >= 0]

        if income <= 0:
            st.error("월 실수령액을 입력해 주세요.")
            return
        if fixed_total + variable_total > income:
            st.error("평소 고정지출과 생활비 합계가 월급보다 큽니다. 입력값을 확인해 주세요.")
            return
        if not request.strip():
            st.error("이번 달 달라진 상황을 입력해 주세요.")
            return

        form_data = {
            "income": int(income),
            "fixed_items": cleaned_fixed,
            "variable_items": cleaned_variable,
            "reduction_rules": reduction_rules,
            "cash": int(cash),
            "savings_assets": int(savings_assets),
            "investment_assets": int(investment_assets),
            "debt": int(debt),
            "savings_rate": float(savings_rate),
            "investment_return": float(investment_return),
            "goal_name": goal_name.strip() or "재무 목표",
            "target_amount": int(target_amount),
            "target_months": int(target_months),
            "risk": risk,
            "request": request.strip(),
        }

        st.session_state.form_data = form_data
        st.session_state.result = calculate_plan(form_data)
        st.session_state.page = "result"
        st.rerun()


def build_donut_chart(result: dict):
    labels = [category for category in CATEGORY_ORDER if result["current_plan"].get(category, 0) > 0]
    values = [result["current_plan"][category] for category in labels]
    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.58,
                marker=dict(colors=CHART_COLORS[:len(labels)]),
                textinfo="label+percent",
                hovertemplate="%{label}<br>%{value:,.0f}원<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title="이번 달 월급 분배",
        showlegend=False,
        height=390,
        margin=dict(t=58, b=20, l=20, r=20),
        annotations=[dict(text="월급 흐름", x=0.5, y=0.5, font_size=16, showarrow=False)],
    )
    return fig


def build_comparison_chart(result: dict):
    categories = ["특별지출", "저축", "투자", "여유자금"]
    base_values = [result["base_plan"][category] for category in categories]
    current_values = [result["current_plan"][category] for category in categories]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="평소 계획", x=categories, y=base_values, marker_color="#98A2B3"))
    fig.add_trace(go.Bar(name="이번 달 계획", x=categories, y=current_values, marker_color="#4E79A7"))
    fig.update_layout(
        title="핵심 항목 비교",
        barmode="group",
        height=360,
        yaxis_title="금액(원)",
        xaxis_title="",
        margin=dict(t=58, b=20, l=20, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(tickformat=",")
    return fig


def build_delta_chart(result: dict):
    rows = list(reversed(result["comparison_rows"]))
    categories = [row["항목"] for row in rows]
    deltas = [row["증감"] for row in rows]
    base_values = [row["평소 계획"] for row in rows]
    current_values = [row["이번 달 계획"] for row in rows]
    colors = [
        "#C01048" if value > 0 else "#175CD3" if value < 0 else "#98A2B3"
        for value in deltas
    ]
    labels = [
        f"+{won(value)}" if value > 0 else f"-{won(abs(value))}" if value < 0 else "변화 없음"
        for value in deltas
    ]

    max_abs = max([abs(value) for value in deltas] + [1])
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=categories,
        x=deltas,
        orientation="h",
        marker_color=colors,
        text=labels,
        textposition="outside",
        cliponaxis=False,
        customdata=list(zip(base_values, current_values)),
        hovertemplate=(
            "%{y}<br>평소 계획: %{customdata[0]:,.0f}원"
            "<br>이번 달 계획: %{customdata[1]:,.0f}원"
            "<br>증감: %{x:,.0f}원<extra></extra>"
        ),
    ))
    fig.add_vline(x=0, line_width=1, line_color="#98A2B3")
    fig.update_layout(
        title="평소 대비 증감",
        height=390,
        xaxis_title="감소 ← 0 → 증가",
        yaxis_title="",
        margin=dict(t=58, b=40, l=20, r=70),
        showlegend=False,
    )
    fig.update_xaxes(
        range=[-max_abs * 1.35, max_abs * 1.35],
        zeroline=True,
        tickformat=",",
    )
    return fig


def get_living_expense_reductions(result: dict) -> list[dict]:
    return [
        row for row in result.get("variable_reductions", [])
        if row.get("항목") not in NON_LIVING_ADJUSTMENT_ITEMS
    ]


def build_variable_reduction_chart(result: dict):
    reductions = get_living_expense_reductions(result)
    if not reductions:
        return None

    rows = list(reversed(reductions))
    categories = [row["항목"] for row in rows]
    values = [row["조정액"] for row in rows]
    labels = [f"-{won(value)}" for value in values]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=categories,
        x=values,
        orientation="h",
        marker_color="#175CD3",
        text=labels,
        textposition="outside",
        cliponaxis=False,
        hovertemplate="%{y}<br>줄인 금액: %{x:,.0f}원<extra></extra>",
    ))
    fig.update_layout(
        title="생활비에서 줄인 금액",
        height=max(280, 72 * len(rows) + 120),
        xaxis_title="절감액(원)",
        yaxis_title="",
        margin=dict(t=58, b=35, l=20, r=70),
        showlegend=False,
    )
    fig.update_xaxes(tickformat=",")
    return fig


def build_projection_chart(result: dict, form: dict):
    history_df = pd.DataFrame(result["projection_history"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=history_df["개월"],
        y=history_df["총자산"],
        mode="lines",
        name="예상 총자산",
        line=dict(width=4, color="#4E79A7"),
        hovertemplate="%{x}개월<br>%{y:,.0f}원<extra></extra>",
    ))
    fig.add_hline(y=form["target_amount"], line_dash="dash", line_color="#E15759", annotation_text="목표 금액")
    fig.update_layout(
        title="목표까지 예상 흐름",
        xaxis_title="개월",
        yaxis_title="예상 금융자산(원)",
        height=360,
        margin=dict(t=58, b=20, l=20, r=20),
    )
    fig.update_yaxes(tickformat=",")
    return fig


def result_page():
    form = st.session_state.form_data
    result = st.session_state.result

    if not form or not result:
        st.session_state.page = "form"
        st.rerun()

    st.title("이번 달 월급 계획 결과 🔎")
    st.caption("이번 달은 조정하고, 다음 달은 평소 기준으로 계획합니다.")

    expected = f"약 {result['expected_months']}개월" if result["expected_months"] >= 0 else "50년 내 달성 어려움"
    target_progress = 1 if form["target_amount"] <= 0 else min(result["total_assets"] / form["target_amount"], 1)

    st.markdown("### 3초 요약")
    current_spending = (
        result["current_plan"].get("고정지출", 0)
        + result["current_plan"].get("생활비", 0)
        + result["current_plan"].get("특별지출", 0)
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        render_money_card("이번 달 쓸 돈", won(current_spending), "조정 반영 후 고정지출·생활비·특별지출 합계")
    with c2:
        render_money_card("이번 달 모을 돈", won(result["current_monthly_contribution"]), "이번 달 저축과 투자 합계")
    with c3:
        render_money_card("목표 달성 예상", expected, f"{form['goal_name']} 기준")

    st.markdown(
        f"""
        <div class="result-box">
        <b>이번 달 상태: {result['status']}</b><br>
        {result['diagnosis_summary']}<br>
        <span class="tiny">{result['priority']} 현재 비상금은 권장 3개월치의 약 {result['emergency_ratio'] * 100:.0f}% 수준입니다.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_badges(result["badges"])

    st.markdown("### 목표 진행률")
    st.progress(target_progress)
    c1, c2, c3 = st.columns(3)
    c1.metric("현재 총자산", won(result["total_assets"]))
    c2.metric("목표 금액", won(form["target_amount"]))
    c3.metric("달성률", pct(target_progress * 100))

    st.markdown("### 이번 달 계획 vs 다음 달 계획")
    c1, c2 = st.columns(2)
    with c1:
        render_plan_card("이번 달 조정 계획", result["current_plan"])
    with c2:
        render_plan_card("다음 달 계획", result["base_plan"])

    st.markdown("### 평소 대비 변화")
    st.caption("0원을 기준으로 왼쪽은 줄어든 항목, 오른쪽은 늘어난 항목입니다.")
    st.plotly_chart(build_delta_chart(result), use_container_width=True)

    with st.expander("항목별 변화 자세히 보기", expanded=False):
        for row in result["comparison_rows"]:
            delta = row["증감"]
            if delta > 0:
                delta_class = "delta-plus"
                delta_text = f"+{won(delta)}"
            elif delta < 0:
                delta_class = "delta-minus"
                delta_text = f"-{won(abs(delta))}"
            else:
                delta_class = "delta-zero"
                delta_text = "변화 없음"
            st.markdown(
                f"""
                <div class="plan-card">
                    <div class="plan-row"><span><b>{row['항목']}</b></span><span class="{delta_class}">{delta_text}</span></div>
                    <div class="plan-row"><span>평소 계획</span><span>{won(row['평소 계획'])}</span></div>
                    <div class="plan-row"><span>이번 달 계획</span><span>{won(row['이번 달 계획'])}</span></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    living_reductions = get_living_expense_reductions(result)
    if living_reductions:
        st.markdown("### 생활비 조정 내역")
        reduction_chart = build_variable_reduction_chart(result)
        if reduction_chart is not None:
            st.plotly_chart(reduction_chart, use_container_width=True)
        reduction_df = pd.DataFrame([
            {"항목": row["항목"], "줄인 금액": won(row["조정액"]), "기준": row["이유"]}
            for row in living_reductions
        ])
        with st.expander("생활비 조정 표로 보기", expanded=False):
            st.dataframe(reduction_df, hide_index=True, use_container_width=True)

    if result.get("uncovered_amount", 0) > 0:
        st.error(f"아직 조정이 필요한 금액이 {won(result['uncovered_amount'])} 남았습니다. 줄일 수 있는 생활비 항목을 더 체크하거나 최소 유지금액을 낮춰 주세요.")

    st.markdown("### 월급 흐름")
    st.plotly_chart(build_donut_chart(result), use_container_width=True)
    st.plotly_chart(build_comparison_chart(result), use_container_width=True)

    st.markdown("### 세부 지출 확인")
    fixed_df = pd.DataFrame([{"항목": item["name"], "금액": won(item["amount"])} for item in form["fixed_items"]])
    variable_df = pd.DataFrame([{"항목": item["name"], "이번 달 금액": won(item["amount"])} for item in result.get("current_variable_items", form["variable_items"])])
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**고정지출**")
        st.dataframe(fixed_df, hide_index=True, use_container_width=True)
    with c2:
        st.markdown("**이번 달 생활비**")
        st.dataframe(variable_df, hide_index=True, use_container_width=True)

    st.markdown("### 장기 목표 예상")
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{form['target_months']}개월 후 예상자산", won(result["projected_at_target"]))
    c2.metric("예상 운용수익", won(result["expected_profit"]))
    c3.metric("목표 부족액", won(result["target_shortfall"]))
    st.plotly_chart(build_projection_chart(result, form), use_container_width=True)

    st.markdown(
        f"""
        <div class="result-box">
        <b>계획 강도: {result['plan_intensity']}</b><br>
        평소 저축·투자율은 월급의 {result['saving_investment_rate']:.1f}%입니다. 
        특별지출이 반복되면 이번 달 조정이 아니라 평소 계획 자체를 다시 설계해야 합니다.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### 이번 달 처방 5가지")
    for idx, action in enumerate(result["actions"], 1):
        st.markdown(f"**{idx}.** {action}")

    with st.expander("계산 근거 자세히 보기", expanded=False):
        st.write(result["explanation"])
        comparison_df = pd.DataFrame(result["comparison_rows"])
        display_df = comparison_df.copy()
        display_df["평소 계획"] = display_df["평소 계획"].map(won)
        display_df["이번 달 계획"] = display_df["이번 달 계획"].map(won)
        display_df["증감"] = display_df["증감"].map(lambda x: f"+{won(x)}" if x > 0 else f"-{won(abs(x))}" if x < 0 else "0원")
        st.dataframe(display_df, hide_index=True, use_container_width=True)

    st.warning(
        "적금 이율은 실제 상품의 세금·우대조건에 따라 달라질 수 있고, 투자 기대수익률은 미래 수익을 보장하지 않습니다. 본 결과는 참고용입니다."
    )

    c1, c2 = st.columns(2)
    if c1.button("세부 항목 수정하기", use_container_width=True):
        st.session_state.page = "form"
        st.rerun()

    if c2.button("처음부터 다시", use_container_width=True):
        st.session_state.page = "home"
        st.session_state.result = None
        st.session_state.form_data = None
        st.session_state.fixed_items_state = default_fixed_items()
        st.session_state.variable_items_state = default_variable_items()
        st.rerun()


init_state()

if st.session_state.page == "home":
    home()
elif st.session_state.page == "form":
    input_form()
else:
    result_page()
