
import json
import math
import os
import re

import pandas as pd
import plotly.express as px
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
    .block-container {max-width: 980px; padding-top: 2rem; padding-bottom: 3rem;}
    .hero {
        padding: 2.2rem 1.6rem;
        border-radius: 24px;
        background: linear-gradient(135deg, #e9f7ff 0%, #f4fbff 55%, #fff8e8 100%);
        border: 1px solid #d8edf8;
        text-align: center;
        margin-bottom: 1.2rem;
    }
    .hero h1 {font-size: 2.45rem; margin-bottom: 0.55rem;}
    .hero p {font-size: 1.06rem; color: #425466;}
    .info-card {
        border: 1px solid #e5e7eb;
        border-radius: 18px;
        padding: 1rem 1.1rem;
        background: white;
        color: #1f2937;
        min-height: 118px;
    }
    .info-card h4 {margin: 0 0 0.35rem 0; color: #111827;}
    .muted {color: #667085; font-size: 0.92rem;}

    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        padding: 14px;
        border-radius: 16px;
    }
    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
        color: #667085 !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #111827 !important;
    }

    .result-box {
        border-radius: 18px;
        padding: 1.05rem 1.15rem;
        background: #f7fbff;
        border: 1px solid #d7eaf8;
        color: #1f2937;
    }
    .result-box b {color: #111827;}
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


def won(value: float) -> str:
    return f"{int(round(value)):,}원"


def init_state():
    defaults = {
        "page": "home",
        "result": None,
        "form_data": None,
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
    }

    label = "특별지출"
    for keyword, value in labels.items():
        if keyword in text:
            label = value
            break

    return label, amount


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

    investment = int(round(available * investment_ratio))

    if emergency_ratio < 1:
        saving = int(round(available * 0.65))
    else:
        saving = int(round(available * 0.50))

    if saving + investment > available * 0.92:
        scale = available * 0.92 / max(saving + investment, 1)
        saving = int(round(saving * scale))
        investment = int(round(investment * scale))

    buffer_money = income - fixed_total - variable_total - saving - investment

    plan = {
        "고정지출": fixed_total,
        "생활비": variable_total,
        "특별지출": 0,
        "저축": max(saving, 0),
        "투자": max(investment, 0),
        "여유자금": max(buffer_money, 0),
    }

    return plan, emergency_ratio, reasons


def adjust_for_special(base_plan: dict, special_amount: int) -> dict:
    """
    평소 계획을 유지하되 특별지출은 이번 달에만
    여유자금 → 투자 → 저축 순으로 조정한다.
    """
    plan = dict(base_plan)
    plan["특별지출"] = max(special_amount, 0)

    remaining = special_amount

    use_buffer = min(plan["여유자금"], remaining)
    plan["여유자금"] -= use_buffer
    remaining -= use_buffer

    use_investment = min(plan["투자"], remaining)
    plan["투자"] -= use_investment
    remaining -= use_investment

    use_saving = min(plan["저축"], remaining)
    plan["저축"] -= use_saving
    remaining -= use_saving

    if remaining > 0:
        reduce_variable = min(plan["생활비"], remaining)
        plan["생활비"] -= reduce_variable
        remaining -= reduce_variable

    return plan


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
    """
    1개월차는 이번 달 조정계획,
    2개월차부터는 평소 계획으로 복귀한다고 가정한다.
    """
    saving_balance = float(savings_assets)
    investment_balance = float(investment_assets)
    cash_balance = float(cash)

    saving_monthly_rate = monthly_rate(savings_rate)
    investment_monthly_rate = monthly_rate(investment_return)

    history = [{
        "개월": 0,
        "총자산": cash_balance + saving_balance + investment_balance,
    }]

    for month in range(1, target_months + 1):
        monthly_saving = current_plan["저축"] if month == 1 else base_plan["저축"]
        monthly_investment = current_plan["투자"] if month == 1 else base_plan["투자"]

        saving_balance = saving_balance * (1 + saving_monthly_rate) + monthly_saving
        investment_balance = investment_balance * (1 + investment_monthly_rate) + monthly_investment

        history.append({
            "개월": month,
            "총자산": cash_balance + saving_balance + investment_balance,
        })

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

    fixed_total = sum(form["fixed_items"].values())
    variable_total = sum(form["variable_items"].values())

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
        special_amount = int(ai_context.get("special_amount") or fallback_amount or 0)
        priority = ai_context.get("priority") or "이번 달의 일시적인 지출만 조정하고 평소 계획은 유지합니다."
    else:
        special_label = fallback_label
        special_amount = fallback_amount
        priority = "평소 저축·투자 계획을 기준으로 이번 달의 일시적인 지출만 조정합니다."

    special_amount = min(max(special_amount, 0), max(income - fixed_total, 0))
    current_plan = adjust_for_special(base_plan, special_amount)

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

    explanation = (
        f"평소에는 매월 저축 {won(base_plan['저축'])}, 투자 {won(base_plan['투자'])}를 유지하는 계획입니다. "
        f"이번 달에는 {special_label} {won(special_amount)}이 발생해 여유자금·투자·저축 순으로 조정했습니다. "
        f"다음 달부터는 다시 평소 계획으로 복귀한다고 가정했습니다."
    )

    weekly_food = form["variable_items"]["식비"] / 4.3
    weekly_social = form["variable_items"]["모임·여가비"] / 4.3
    emergency_target = (fixed_total + variable_total) * 3

    actions = [
        (
            f"월급일에 이번 달 저축 {won(current_plan['저축'])}과 투자 {won(current_plan['투자'])}를 먼저 분리하세요. "
            f"평소 기준은 저축 {won(base_plan['저축'])}, 투자 {won(base_plan['투자'])}이며 이번 달만 일시적으로 조정된 금액입니다."
        ),
        (
            f"{special_label} 비용 {won(special_amount)}은 별도 통장이나 봉투에 즉시 분리하세요. "
            "생활비 계좌와 섞이지 않게 해야 추가 지출을 막을 수 있습니다."
            if special_amount > 0
            else "이번 달 특별지출이 없으므로 평소 월급 계획을 그대로 실행하세요."
        ),
        (
            f"식비는 주당 약 {won(weekly_food)}, 모임·여가비는 주당 약 {won(weekly_social)}를 한도로 설정하세요. "
            "주간 단위로 관리하면 월말 초과지출을 줄이기 쉽습니다."
        ),
        (
            f"이번 달 투자금은 {won(current_plan['투자'])}까지만 집행하고, 다음 달에는 평소 투자금 "
            f"{won(base_plan['투자'])}로 복귀하세요. 연 {investment_return:.1f}%는 확정수익이 아닌 계획용 가정입니다."
        ),
        (
            f"월말에 현금성 자산이 권장 비상금 {won(emergency_target)} 대비 "
            f"{emergency_ratio * 100:.0f}% 수준인지 확인하세요. 특별지출이 반복되면 다음 달 평소 계획 자체를 다시 조정해야 합니다."
        ),
    ]

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
        "projection_history": projection_history,
        "expected_months": expected_months,
        "explanation": explanation,
        "actions": actions,
        "adjustment_reasons": adjustment_reasons,
        "ai_used": ai_context is not None,
    }


def home():
    st.markdown(
        """
        <div class="hero">
            <h1>💸 월급아 어디가니?</h1>
            <p><b>평소 월급 계획을 만들고,<br>
            이번 달 달라진 상황까지 반영해 드립니다.</b></p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            '<div class="info-card"><h4>📅 평소 계획</h4><div class="muted">매월 유지할 저축·투자 기준을 만듭니다.</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            '<div class="info-card"><h4>✨ 이번 달 조정</h4><div class="muted">생신·여행·병원비 같은 일시 지출을 반영합니다.</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            '<div class="info-card"><h4>📈 장기 목표</h4><div class="muted">다음 달부터 평소 계획으로 복귀해 목표를 계산합니다.</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    if st.button("내 월급 계획 만들기", type="primary", use_container_width=True):
        st.session_state.page = "form"
        st.rerun()

    st.caption("입력 정보는 현재 세션에서만 사용되며 별도로 저장하지 않습니다.")


def input_form():
    st.title("내 월급 계획 만들기")
    st.caption("평소 지출과 이번 달의 달라진 상황을 함께 입력하세요.")

    with st.form("salary_form"):
        st.subheader("1. 월급")
        income = st.number_input(
            "월 실수령액",
            min_value=0,
            value=3_500_000,
            step=100_000,
            format="%d",
        )

        st.subheader("2. 평소 고정지출")
        c1, c2 = st.columns(2)
        housing = c1.number_input("주거비·관리비", min_value=0, value=0, step=50_000, format="%d")
        telecom = c2.number_input("통신비", min_value=0, value=80_000, step=10_000, format="%d")
        transport = c1.number_input("교통비", min_value=0, value=50_000, step=10_000, format="%d")
        insurance = c2.number_input("보험료", min_value=0, value=100_000, step=10_000, format="%d")
        subscriptions = c1.number_input("구독료", min_value=0, value=30_000, step=10_000, format="%d")
        other_fixed = c2.number_input("기타 고정지출", min_value=0, value=40_000, step=10_000, format="%d")

        st.subheader("3. 평소 생활비")
        c1, c2 = st.columns(2)
        food = c1.number_input("식비", min_value=0, value=350_000, step=20_000, format="%d")
        cafe = c2.number_input("카페·간식", min_value=0, value=100_000, step=10_000, format="%d")
        social = c1.number_input("모임·여가비", min_value=0, value=150_000, step=20_000, format="%d")
        shopping = c2.number_input("쇼핑·생활용품", min_value=0, value=100_000, step=20_000, format="%d")
        other_variable = c1.number_input("기타 생활비", min_value=0, value=0, step=10_000, format="%d")

        st.subheader("4. 현재 자산")
        c1, c2 = st.columns(2)
        cash = c1.number_input("현금·입출금 통장", min_value=0, value=3_000_000, step=100_000, format="%d")
        savings_assets = c2.number_input("예금·적금", min_value=0, value=5_000_000, step=100_000, format="%d")
        investment_assets = c1.number_input("주식·ETF", min_value=0, value=2_000_000, step=100_000, format="%d")
        debt = c2.number_input("대출 잔액", min_value=0, value=0, step=100_000, format="%d")

        st.subheader("5. 수익률 가정")
        c1, c2 = st.columns(2)
        savings_rate = c1.number_input(
            "예금·적금 연 이율(%)",
            min_value=0.0,
            max_value=20.0,
            value=4.0,
            step=0.1,
            help="현재 또는 예상 상품의 세전 연 이율을 입력하세요.",
        )
        investment_return = c2.number_input(
            "투자 연평균 기대수익률(%)",
            min_value=-20.0,
            max_value=30.0,
            value=6.0,
            step=0.5,
            help="확정수익률이 아닌 장기 계획용 가정값입니다.",
        )

        st.subheader("6. 목표와 투자 성향")
        c1, c2 = st.columns(2)
        goal_name = c1.text_input("재무 목표", value="목돈 마련")
        target_amount = c2.number_input("목표 금액", min_value=0, value=50_000_000, step=1_000_000, format="%d")
        target_months = c1.number_input("목표 기간(개월)", min_value=1, value=36, step=1)
        risk = c2.selectbox("투자 성향", list(RISK_RATIOS.keys()), index=2)

        st.subheader("7. 이번 달 달라진 상황")
        request = st.text_area(
            "이번 달에만 발생한 지출이나 고민을 적어주세요.",
            value="이번 달은 부모님 생신이라 50만 원 정도 추가로 필요해. 평소 목표는 유지하면서 이번 달만 조정해줘.",
            height=120,
            help="예: 다음 달 여행 예약금으로 이번 달 30만 원이 더 필요해.",
        )

        submitted = st.form_submit_button("평소 계획과 이번 달 계획 비교하기", type="primary", use_container_width=True)

    if st.button("← 시작화면으로"):
        st.session_state.page = "home"
        st.rerun()

    if submitted:
        fixed_items = {
            "주거비·관리비": int(housing),
            "통신비": int(telecom),
            "교통비": int(transport),
            "보험료": int(insurance),
            "구독료": int(subscriptions),
            "기타 고정지출": int(other_fixed),
        }
        variable_items = {
            "식비": int(food),
            "카페·간식": int(cafe),
            "모임·여가비": int(social),
            "쇼핑·생활용품": int(shopping),
            "기타 생활비": int(other_variable),
        }

        if income <= 0:
            st.error("월 실수령액을 입력해 주세요.")
            return

        if sum(fixed_items.values()) + sum(variable_items.values()) > income:
            st.error("평소 고정지출과 생활비 합계가 월급보다 큽니다. 입력값을 확인해 주세요.")
            return

        if not request.strip():
            st.error("이번 달 달라진 상황을 입력해 주세요.")
            return

        form_data = {
            "income": int(income),
            "fixed_items": fixed_items,
            "variable_items": variable_items,
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


def result_page():
    form = st.session_state.form_data
    result = st.session_state.result

    if not form or not result:
        st.session_state.page = "form"
        st.rerun()

    st.title("평소 계획과 이번 달 계획을 비교했어요 🔎")
    st.caption("이번 달만 조정하고, 다음 달부터는 평소 계획으로 복귀하는 기준입니다.")

    c1, c2, c3 = st.columns(3)
    c1.metric("총자산", won(result["total_assets"]))
    c2.metric("순자산", won(result["net_assets"]))
    c3.metric("이번 달 특별지출", won(result["special_amount"]))

    st.markdown(
        f"""
        <div class="result-box">
        <b>AI 한 줄 진단</b><br>
        {result['priority']} 현재 비상금은 권장 3개월치의 약 {result['emergency_ratio'] * 100:.0f}% 수준입니다.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("평소 계획 vs 이번 달 계획")

    comparison_df = pd.DataFrame(result["comparison_rows"])
    display_df = comparison_df.copy()
    display_df["평소 계획"] = display_df["평소 계획"].map(won)
    display_df["이번 달 계획"] = display_df["이번 달 계획"].map(won)
    display_df["증감"] = display_df["증감"].map(
        lambda x: f"+{won(x)}" if x > 0 else won(x)
    )
    st.dataframe(display_df, hide_index=True, use_container_width=True)

    comparison_chart_categories = {"특별지출", "저축", "투자", "여유자금"}
    chart_df = pd.DataFrame([
        {
            "항목": row["항목"],
            "금액": row["평소 계획"],
            "구분": "평소 계획",
        }
        for row in result["comparison_rows"]
        if row["항목"] in comparison_chart_categories and row["평소 계획"] > 0
    ] + [
        {
            "항목": row["항목"],
            "금액": row["이번 달 계획"],
            "구분": "이번 달 계획",
        }
        for row in result["comparison_rows"]
        if row["항목"] in comparison_chart_categories and row["이번 달 계획"] > 0
    ])

    fig = px.bar(
        chart_df,
        x="항목",
        y="금액",
        color="구분",
        barmode="group",
    )
    fig.update_layout(
        margin=dict(t=20, b=20, l=20, r=20),
        yaxis_title="금액(원)",
        xaxis_title="",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("이번 달 조정 핵심")
    c1, c2, c3 = st.columns(3)
    c1.metric("평소 저축·투자", won(result["base_monthly_contribution"]))
    c2.metric("이번 달 저축·투자", won(result["current_monthly_contribution"]))
    c3.metric("이번 달 일시 감소", won(result["one_time_reduction"]))

    st.write(result["explanation"])

    st.subheader("세부 지출 확인")
    fixed_df = pd.DataFrame(
        [{"항목": k, "금액": won(v)} for k, v in form["fixed_items"].items()]
    )
    variable_df = pd.DataFrame(
        [{"항목": k, "금액": won(v)} for k, v in form["variable_items"].items()]
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**고정지출**")
        st.dataframe(fixed_df, hide_index=True, use_container_width=True)
    with c2:
        st.markdown("**생활비**")
        st.dataframe(variable_df, hide_index=True, use_container_width=True)

    st.subheader("장기 목표 예상")
    c1, c2 = st.columns(2)
    expected = (
        f"약 {result['expected_months']}개월"
        if result["expected_months"] >= 0
        else "50년 내 달성 어려움"
    )
    c1.metric("목표 달성 예상 기간", expected)
    c2.metric(f"{form['target_months']}개월 후 예상자산", won(result["projected_at_target"]))

    st.caption(
        f"이번 달은 조정 계획, 다음 달부터는 평소 계획으로 계산 | "
        f"적금 연 {form['savings_rate']:.1f}% · 투자 연 {form['investment_return']:.1f}% 가정"
    )

    history_df = pd.DataFrame(result["projection_history"])
    fig_line = go.Figure()
    fig_line.add_trace(go.Scatter(
        x=history_df["개월"],
        y=history_df["총자산"],
        mode="lines",
        name="예상 총자산",
    ))
    fig_line.add_hline(
        y=form["target_amount"],
        line_dash="dash",
        annotation_text="목표 금액",
    )
    fig_line.update_layout(
        xaxis_title="개월",
        yaxis_title="예상 금융자산(원)",
        margin=dict(t=20, b=20, l=20, r=20),
    )
    st.plotly_chart(fig_line, use_container_width=True)

    st.subheader("이번 달 실행 계획 5가지")
    for idx, action in enumerate(result["actions"], 1):
        st.markdown(f"**{idx}. {action}**")

    st.warning(
        "적금 이율은 실제 상품의 세금·우대조건에 따라 달라질 수 있고, "
        "투자 기대수익률은 미래 수익을 보장하지 않습니다. 본 결과는 참고용입니다."
    )

    c1, c2 = st.columns(2)
    if c1.button("세부 항목 수정하기", use_container_width=True):
        st.session_state.page = "form"
        st.rerun()

    if c2.button("처음부터 다시", use_container_width=True):
        st.session_state.page = "home"
        st.session_state.result = None
        st.session_state.form_data = None
        st.rerun()


init_state()

if st.session_state.page == "home":
    home()
elif st.session_state.page == "form":
    input_form()
else:
    result_page()
