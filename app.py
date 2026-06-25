
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
    .block-container {max-width: 920px; padding-top: 2rem; padding-bottom: 3rem;}
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


def extract_special_expense(text: str) -> tuple[str, int]:
    """간단한 한국어 금액 표현을 찾아 특별지출 이름과 금액을 반환한다."""
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

    label_candidates = {
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
    for keyword, candidate in label_candidates.items():
        if keyword in text:
            label = candidate
            break
    return label, amount


def ask_ai_for_context(form: dict) -> dict | None:
    """API 키가 있을 때 자유 입력에서 특별지출과 우선순위를 구조화한다."""
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
사용자의 월급 관리 요청을 분석해 JSON만 반환하세요.

사용자 요청: {form['request']}

반환 형식:
{{
  "special_event": "특별 상황 이름 또는 없음",
  "special_amount": 숫자,
  "priority": "사용자의 핵심 우선순위 한 문장"
}}

규칙:
- 금액은 원 단위 숫자로 반환
- 명시된 특별지출 금액이 없으면 0
- 특정 투자상품이나 종목을 추천하지 않음
"""
    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": "당신은 한국어 재무 요청을 구조화하는 도우미입니다. JSON만 반환하세요.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw = response.output_text.strip()
        raw = re.sub(r"^```json\s*|\s*```$", "", raw)
        return json.loads(raw)
    except Exception:
        return None


def monthly_rate(annual_percent: float) -> float:
    """연 수익률을 월 복리 수익률로 변환한다."""
    annual_decimal = annual_percent / 100
    return (1 + annual_decimal) ** (1 / 12) - 1


def project_assets(
    months: int,
    cash: float,
    savings_assets: float,
    investment_assets: float,
    monthly_saving: float,
    monthly_investment: float,
    savings_rate: float,
    investment_return: float,
) -> tuple[float, list[dict]]:
    """현재 자산과 월 납입액을 월 복리로 예상한다."""
    saving_balance = float(savings_assets)
    investment_balance = float(investment_assets)
    cash_balance = float(cash)
    saving_monthly_rate = monthly_rate(savings_rate)
    investment_monthly_rate = monthly_rate(investment_return)

    history = [{
        "개월": 0,
        "현금": cash_balance,
        "예금·적금": saving_balance,
        "주식·ETF": investment_balance,
        "총자산": cash_balance + saving_balance + investment_balance,
    }]

    for month in range(1, months + 1):
        saving_balance = saving_balance * (1 + saving_monthly_rate) + monthly_saving
        investment_balance = investment_balance * (1 + investment_monthly_rate) + monthly_investment
        history.append({
            "개월": month,
            "현금": cash_balance,
            "예금·적금": saving_balance,
            "주식·ETF": investment_balance,
            "총자산": cash_balance + saving_balance + investment_balance,
        })

    return history[-1]["총자산"], history


def months_to_target(
    target_amount: float,
    cash: float,
    savings_assets: float,
    investment_assets: float,
    monthly_saving: float,
    monthly_investment: float,
    savings_rate: float,
    investment_return: float,
    max_months: int = 600,
) -> int:
    """예상수익률을 반영해 목표금액까지 필요한 개월 수를 찾는다."""
    current_total = cash + savings_assets + investment_assets
    if current_total >= target_amount:
        return 0
    if monthly_saving + monthly_investment <= 0:
        return -1

    saving_balance = float(savings_assets)
    investment_balance = float(investment_assets)
    saving_monthly_rate = monthly_rate(savings_rate)
    investment_monthly_rate = monthly_rate(investment_return)

    for month in range(1, max_months + 1):
        saving_balance = saving_balance * (1 + saving_monthly_rate) + monthly_saving
        investment_balance = investment_balance * (1 + investment_monthly_rate) + monthly_investment
        if cash + saving_balance + investment_balance >= target_amount:
            return month
    return -1


def required_monthly_contribution(
    target_amount: float,
    target_months: int,
    cash: float,
    savings_assets: float,
    investment_assets: float,
    saving_share: float,
    savings_rate: float,
    investment_return: float,
) -> float:
    """목표기간 내 달성을 위한 월 총 적립액을 이분탐색으로 계산한다."""
    current_total = cash + savings_assets + investment_assets
    if current_total >= target_amount:
        return 0

    low, high = 0.0, max(target_amount, 1.0)
    for _ in range(70):
        mid = (low + high) / 2
        projected, _ = project_assets(
            target_months,
            cash,
            savings_assets,
            investment_assets,
            mid * saving_share,
            mid * (1 - saving_share),
            savings_rate,
            investment_return,
        )
        if projected >= target_amount:
            high = mid
        else:
            low = mid
    return math.ceil(high)


def calculate_plan(form: dict) -> dict:
    income = form["income"]
    fixed = form["fixed"]
    living = form["living"]
    cash = form["cash"]
    savings_assets = form["savings_assets"]
    investment_assets = form["investment_assets"]
    debt = form["debt"]
    target_amount = form["target_amount"]
    target_months = max(form["target_months"], 1)
    risk = form["risk"]
    savings_rate = form["savings_rate"]
    investment_return = form["investment_return"]

    total_assets = cash + savings_assets + investment_assets
    net_assets = total_assets - debt
    available_before_special = max(income - fixed - living, 0)

    ai_context = ask_ai_for_context(form)
    fallback_label, fallback_amount = extract_special_expense(form["request"])
    if ai_context:
        special_label = ai_context.get("special_event") or fallback_label
        special_amount = int(ai_context.get("special_amount") or fallback_amount or 0)
        priority = ai_context.get("priority") or "현재 상황을 반영해 균형 있게 조정합니다."
    else:
        special_label = fallback_label
        special_amount = fallback_amount
        priority = "현재 상황, 목표 기간, 투자 성향을 함께 반영해 이번 달 계획을 조정합니다."

    special_amount = min(max(special_amount, 0), max(income - fixed, 0))

    emergency_target = max((fixed + living) * 3, 1)
    emergency_ratio = cash / emergency_target

    invest_ratio = RISK_RATIOS[risk]
    adjustment_reasons = []
    if emergency_ratio < 0.5:
        invest_ratio *= 0.35
        adjustment_reasons.append("비상금 부족")
    elif emergency_ratio < 1:
        invest_ratio *= 0.65
        adjustment_reasons.append("비상금 보완 필요")
    if debt > total_assets * 0.5 and debt > 0:
        invest_ratio *= 0.6
        adjustment_reasons.append("부채 부담")
    if target_months <= 12:
        invest_ratio *= 0.55
        adjustment_reasons.append("단기 목표")
    if special_amount > available_before_special * 0.4 and special_amount > 0:
        invest_ratio *= 0.65
        adjustment_reasons.append("큰 특별지출")

    after_essentials = max(income - fixed - living - special_amount, 0)

    # 비상금이 부족하면 저축 비중을 높이고, 충분하면 투자 성향을 더 반영한다.
    if emergency_ratio < 1:
        investment = after_essentials * invest_ratio
        saving = after_essentials * 0.70
        if saving + investment > after_essentials * 0.92:
            scale = (after_essentials * 0.92) / max(saving + investment, 1)
            saving *= scale
            investment *= scale
    else:
        investment = after_essentials * invest_ratio
        saving = min(after_essentials * 0.55, after_essentials - investment)
        if saving + investment > after_essentials * 0.92:
            saving = max(after_essentials * 0.92 - investment, 0)

    budget = {
        "고정지출": int(round(fixed)),
        "생활비": int(round(living)),
        "특별지출": int(round(special_amount)),
        "저축": int(round(max(saving, 0))),
        "투자": int(round(max(investment, 0))),
        "여유자금": 0,
    }
    budget["여유자금"] = int(income - sum(v for k, v in budget.items() if k != "여유자금"))

    if budget["여유자금"] < 0:
        shortage = -budget["여유자금"]
        reduce_invest = min(budget["투자"], shortage)
        budget["투자"] -= reduce_invest
        shortage -= reduce_invest
        reduce_saving = min(budget["저축"], shortage)
        budget["저축"] -= reduce_saving
        shortage -= reduce_saving
        if shortage > 0:
            budget["생활비"] = max(budget["생활비"] - shortage, 0)
        budget["여유자금"] = income - sum(v for k, v in budget.items() if k != "여유자금")

    monthly_total_contribution = budget["저축"] + budget["투자"]
    saving_share = (
        budget["저축"] / monthly_total_contribution
        if monthly_total_contribution > 0
        else 1.0
    )

    required_monthly = required_monthly_contribution(
        target_amount=target_amount,
        target_months=target_months,
        cash=cash,
        savings_assets=savings_assets,
        investment_assets=investment_assets,
        saving_share=saving_share,
        savings_rate=savings_rate,
        investment_return=investment_return,
    )

    expected_months = months_to_target(
        target_amount=target_amount,
        cash=cash,
        savings_assets=savings_assets,
        investment_assets=investment_assets,
        monthly_saving=budget["저축"],
        monthly_investment=budget["투자"],
        savings_rate=savings_rate,
        investment_return=investment_return,
    )

    projected_at_target, projection_history = project_assets(
        target_months,
        cash,
        savings_assets,
        investment_assets,
        budget["저축"],
        budget["투자"],
        savings_rate,
        investment_return,
    )

    if special_amount:
        explanation = (
            f"{special_label} {won(special_amount)}을 우선 반영한 뒤, "
            f"저축 {won(budget['저축'])}과 투자 {won(budget['투자'])}로 나눴습니다. "
            f"적금 연 {savings_rate:.1f}%, 투자 연 {investment_return:.1f}%의 가정 수익률을 적용하면 "
            f"{target_months}개월 후 예상 금융자산은 약 {won(projected_at_target)}입니다."
        )
    else:
        explanation = (
            f"{risk} 성향과 비상금 수준을 반영해 저축 {won(budget['저축'])}, "
            f"투자 {won(budget['투자'])}로 배분했습니다. "
            f"적금 연 {savings_rate:.1f}%, 투자 연 {investment_return:.1f}%의 가정 수익률을 적용하면 "
            f"{target_months}개월 후 예상 금융자산은 약 {won(projected_at_target)}입니다."
        )

    weekly_living = budget["생활비"] / 4.3 if budget["생활비"] else 0
    daily_living = budget["생활비"] / 30 if budget["생활비"] else 0
    action_2 = (
        f"{special_label} 예산 {won(budget['특별지출'])}을 월급을 받은 당일 별도 통장이나 공간으로 옮겨 "
        "생활비와 섞이지 않게 관리하세요."
        if budget["특별지출"] > 0
        else f"생활비를 주당 약 {won(weekly_living)}로 나누고, 매주 초 해당 금액만 생활비 계좌로 옮기세요."
    )

    actions = [
        (
            f"월급일 당일 저축 {won(budget['저축'])}을 예금·적금 계좌로 자동이체하세요. "
            f"설정한 연 {savings_rate:.1f}% 이율은 만기까지 유지된다는 가정이므로 실제 상품 조건도 확인하세요."
        ),
        action_2,
        (
            f"이번 달 투자 한도를 {won(budget['투자'])}로 고정하고 2~4회로 나누어 투자하세요. "
            f"연 {investment_return:.1f}%는 예상수익률일 뿐 확정수익이 아니므로 단기 지출 예정 자금은 투자하지 마세요."
        ),
        (
            f"생활비는 하루 평균 약 {won(daily_living)}를 기준으로 사용하고, 매주 말 실제 지출과 비교해 "
            "다음 주 한도를 조정하세요."
        ),
        (
            f"월말에 현금성 자산이 권장 비상금 {won(emergency_target)}의 "
            f"{emergency_ratio * 100:.0f}% 수준에서 얼마나 개선됐는지 확인하고, 다음 달 저축·투자 비중을 다시 설정하세요."
        ),
    ]

    return {
        "total_assets": total_assets,
        "net_assets": net_assets,
        "available": max(income - fixed - living - special_amount, 0),
        "emergency_ratio": emergency_ratio,
        "emergency_target": emergency_target,
        "special_label": special_label,
        "special_amount": special_amount,
        "priority": priority,
        "budget": budget,
        "required_monthly": required_monthly,
        "expected_months": expected_months,
        "projected_at_target": projected_at_target,
        "projection_history": projection_history,
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
            <p><b>현재 자산과 이번 달 상황을 입력하면<br>
            AI가 생활비·저축·투자 계획을 설계해 드립니다.</b></p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            '<div class="info-card"><h4>🧾 현재 상태</h4><div class="muted">현금·적금·주식·대출을 한눈에 정리합니다.</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            '<div class="info-card"><h4>🗺️ 맞춤 배분</h4><div class="muted">월급을 생활비·저축·투자로 나눠드립니다.</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            '<div class="info-card"><h4>📈 목표 예상</h4><div class="muted">적금 이율과 투자 기대수익률을 반영합니다.</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    if st.button("내 월급 계획 만들기", type="primary", use_container_width=True):
        st.session_state.page = "form"
        st.rerun()

    st.caption("입력 정보는 현재 세션에서만 사용되며 별도로 저장하지 않습니다.")


def input_form():
    st.title("내 월급 계획 만들기")
    st.caption("핵심 숫자와 이번 달 고민만 입력하면 됩니다.")

    with st.form("salary_form"):
        st.subheader("1. 월급과 지출")
        c1, c2, c3 = st.columns(3)
        income = c1.number_input("월 실수령액", min_value=0, value=3_500_000, step=100_000, format="%d")
        fixed = c2.number_input("월 고정지출", min_value=0, value=800_000, step=50_000, format="%d")
        living = c3.number_input("월 평균 생활비", min_value=0, value=700_000, step=50_000, format="%d")

        st.subheader("2. 현재 자산")
        c1, c2 = st.columns(2)
        cash = c1.number_input("현금·입출금 통장", min_value=0, value=3_000_000, step=100_000, format="%d")
        savings_assets = c2.number_input("예금·적금", min_value=0, value=5_000_000, step=100_000, format="%d")
        investment_assets = c1.number_input("주식·ETF", min_value=0, value=2_000_000, step=100_000, format="%d")
        debt = c2.number_input("대출 잔액", min_value=0, value=0, step=100_000, format="%d")

        st.subheader("3. 수익률 가정")
        c1, c2 = st.columns(2)
        savings_rate = c1.number_input(
            "예금·적금 연 이율(%)",
            min_value=0.0,
            max_value=20.0,
            value=4.0,
            step=0.1,
            help="현재 가입 상품 또는 예상 상품의 세전 연 이율을 입력하세요.",
        )
        investment_return = c2.number_input(
            "투자 연평균 기대수익률(%)",
            min_value=-20.0,
            max_value=30.0,
            value=6.0,
            step=0.5,
            help="확정 수익률이 아닌 장기 계획용 가정입니다. 보수적으로 입력하는 것을 권장합니다.",
        )
        st.caption("투자 기대수익률은 미래 수익을 보장하지 않는 가정값입니다. 단기 목표일수록 낮게 설정하세요.")

        st.subheader("4. 목표와 투자 성향")
        c1, c2 = st.columns(2)
        goal_name = c1.text_input("재무 목표", value="목돈 마련")
        target_amount = c2.number_input("목표 금액", min_value=0, value=50_000_000, step=1_000_000, format="%d")
        target_months = c1.number_input("목표 기간(개월)", min_value=1, value=36, step=1)
        risk = c2.selectbox("투자 성향", list(RISK_RATIOS.keys()), index=2)

        st.subheader("5. AI에게 자유롭게 요청하기")
        request = st.text_area(
            "이번 달 상황이나 고민을 자유롭게 적어주세요.",
            value="이번 달은 부모님 생신이라 50만 원 정도 써야 해. 내 상황에 맞게 이번 달 계획을 짜줘.",
            height=120,
            help="예: 다음 달 여행을 가는데 저축과 투자 비중을 어떻게 조정할까?",
        )

        submitted = st.form_submit_button("AI에게 계획 받기", type="primary", use_container_width=True)

    if st.button("← 시작화면으로"):
        st.session_state.page = "home"
        st.rerun()

    if submitted:
        if income <= 0:
            st.error("월 실수령액을 입력해 주세요.")
            return
        if fixed + living > income:
            st.error("고정지출과 생활비가 월급보다 큽니다. 입력값을 확인해 주세요.")
            return
        if not request.strip():
            st.error("이번 달 상황이나 고민을 입력해 주세요.")
            return

        form_data = {
            "income": int(income),
            "fixed": int(fixed),
            "living": int(living),
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

    st.title("월급의 행방을 찾았어요! 🔎")
    st.caption("입력한 상황과 수익률 가정을 반영한 이번 달 추천안입니다.")

    c1, c2, c3 = st.columns(3)
    c1.metric("총자산", won(result["total_assets"]))
    c2.metric("순자산", won(result["net_assets"]))
    c3.metric("특별지출 반영 후 가용금액", won(result["available"]))

    if result["ai_used"]:
        st.success("AI가 자유 입력의 특별 상황과 우선순위를 분석했습니다.")
    else:
        st.info("데모 분석 모드입니다. API 키를 연결하면 자유 입력을 더 정교하게 해석합니다.")

    st.markdown(
        f"""
        <div class="result-box">
        <b>AI 한 줄 진단</b><br>
        {result['priority']} 비상금은 권장 3개월치의 약 {result['emergency_ratio']*100:.0f}% 수준입니다.
        </div>
        """,
        unsafe_allow_html=True,
    )

    if result["adjustment_reasons"]:
        st.caption("투자 비중 조정 요인: " + ", ".join(result["adjustment_reasons"]))

    st.subheader("이번 달 추천 월급 배분")
    chart_df = pd.DataFrame(
        [{"항목": key, "금액": result["budget"][key]} for key in CATEGORY_ORDER if result["budget"][key] > 0]
    )
    fig = px.pie(chart_df, names="항목", values="금액", hole=0.55)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), legend_title_text="")
    st.plotly_chart(fig, use_container_width=True)

    table = []
    for category in CATEGORY_ORDER:
        amount = result["budget"][category]
        table.append({
            "항목": category,
            "추천 금액": won(amount),
            "월급 대비": f"{amount / form['income'] * 100:.1f}%",
        })
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)

    st.subheader("왜 이렇게 나눴나요?")
    st.write(result["explanation"])

    st.subheader("목표 달성 분석")
    c1, c2, c3 = st.columns(3)
    c1.metric("목표기간 내 필요 월 적립액", won(result["required_monthly"]))
    expected = (
        f"약 {result['expected_months']}개월"
        if result["expected_months"] >= 0
        else "50년 내 달성 어려움"
    )
    c2.metric("추천안 기준 예상 기간", expected)
    c3.metric(f"{form['target_months']}개월 후 예상자산", won(result["projected_at_target"]))
    st.caption(
        f"목표: {form['goal_name']} · {won(form['target_amount'])} | "
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
        "적금 이율은 실제 상품의 세금·우대조건에 따라 달라질 수 있고, 투자 기대수익률은 미래 수익을 보장하지 않습니다. "
        "본 결과는 개인 예산 설계를 위한 참고용입니다."
    )

    c1, c2 = st.columns(2)
    if c1.button("입력값 수정하기", use_container_width=True):
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
