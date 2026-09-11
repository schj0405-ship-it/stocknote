import concurrent.futures
from datetime import date

import pandas as pd
import streamlit as st

from auth import get_supabase_client, require_login
from get_financial_data import find_stock_code
from stock_price import get_current_price

st.set_page_config(page_title="스톡노트 - 투자내역", layout="wide")
st.title("투자내역 입력")

# 로그인 안 되어 있으면 여기서 화면 실행이 멈추고, 로그인/회원가입 화면만 보여줍니다.
user = require_login()

# 로그인한 사용자의 인증 정보가 실려있는 연결 객체입니다.
# (이 객체로 trades 테이블에 접근하면, Supabase가 자동으로 "이 사람이 맞는지" 확인합니다.)
supabase = get_supabase_client()

# 표에서 쓰는 화면 표시용 번호/손익 칸 이름 (DB에는 저장되지 않는, 화면에서만 계산해서 보여주는 칸)
DISPLAY_NO_COL = "번호"
PROFIT_COL = "손익"

# 흰색 배경에서 이익(초록)·손실(빨강)을 또렷하게 보여주기 위한 색상.
# 1_재무데이터_조회.py의 증감률 배지 색과 통일했습니다.
PROFIT_COLOR = "#15803d"
LOSS_COLOR = "#b91c1c"


def _style_profit_cell(value):
    """양수(이익)는 초록, 음수(손실)는 빨강 글자로 칠해주는 함수. 여러 표에서 재사용합니다."""
    if pd.isna(value):
        return ""
    if value > 0:
        return f"color: {PROFIT_COLOR}; font-weight: 700"
    if value < 0:
        return f"color: {LOSS_COLOR}; font-weight: 700"
    return ""


def _apply_profit_style(styler, subset):
    # pandas 2.1부터는 applymap 대신 map을 쓰라고 권장하는데, 배포 서버의
    # pandas 버전이 정확히 몇인지 고정돼 있지 않아서 둘 다 지원하도록 처리합니다.
    if hasattr(styler, "map"):
        return styler.map(_style_profit_cell, subset=subset)
    return styler.applymap(_style_profit_cell, subset=subset)


def load_trades():
    """로그인한 사용자 본인의 투자내역만 불러옵니다."""
    response = (
        supabase.table("trades")
        .select("*")
        .eq("user_id", user.id)
        .order("id", desc=False)  # 가장 먼저 저장한 것부터 순서대로 받아옵니다.
        .execute()
    )
    df = pd.DataFrame(response.data)
    if df.empty:
        return df

    # 날짜 글자(TEXT)를 화면에서 달력으로 고를 수 있는 날짜 형식으로 바꿔줍니다.
    df["buy_date"] = pd.to_datetime(df["buy_date"], errors="coerce").dt.date
    df["sell_date"] = pd.to_datetime(df["sell_date"], errors="coerce").dt.date
    # 화면에는 본인 데이터만 보이므로 user_id 칸은 굳이 보여줄 필요가 없어 뺍니다.
    df = df.drop(columns=["user_id"])

    # DB가 자동으로 매기는 id는 행을 지우면 번호에 구멍이 생깁니다(예: 1, 2, 4, 7...).
    # 화면 맨 앞 번호 칸은 "지금 저장된 내용이 몇 개인지"만 보여주도록,
    # id 대신 저장된 순서 그대로 1, 2, 3...으로 새로 번호를 매깁니다.
    df[DISPLAY_NO_COL] = range(1, len(df) + 1)
    df = df.drop(columns=["id"])

    # sell_quantity(매도수량) 칸은 새로 추가된 것이라, Supabase에 아직
    # 이 칸을 추가하는 SQL을 실행하지 않았다면 응답에 이 칸 자체가 없을 수
    # 있습니다. 그런 경우에도 화면이 에러 없이 뜨도록, 예전 방식(매도가가
    # 있으면 산 만큼 전부 팔았다고 가정)으로 임시로 채워 넣습니다.
    # (다만 실제로 저장하려면 반드시 SQL을 먼저 실행해야 합니다 - 안내 문구 참고)
    if "sell_quantity" not in df.columns:
        df["sell_quantity"] = df.apply(
            lambda r: r.get("quantity", 0) if (r.get("sell_price") or 0) > 0 else 0,
            axis=1,
        )
    else:
        df["sell_quantity"] = df["sell_quantity"].fillna(0)

    # 매도수량이 0보다 큰(=조금이라도 매도한) 행만 손익을 계산합니다.
    # 손익 = (매도가 - 매수가) × 매도수량 - 수수료 - 세금
    # (매도수량이 아니라 매입수량으로 계산하면, 일부만 판 경우 손익이 부풀려집니다.)
    def _row_profit(row):
        sell_price = row.get("sell_price") or 0
        sell_quantity = row.get("sell_quantity") or 0
        if sell_price > 0 and sell_quantity > 0:
            buy_price = row.get("buy_price") or 0
            fee = row.get("fee") or 0
            tax = row.get("tax") or 0
            return (sell_price - buy_price) * sell_quantity - fee - tax
        return None

    df[PROFIT_COL] = df.apply(_row_profit, axis=1)

    column_order = [
        DISPLAY_NO_COL,
        "stock_name",
        "stock_code",
        "buy_date",
        "buy_price",
        "quantity",
        "sell_date",
        "sell_price",
        "sell_quantity",
        "fee",
        "tax",
        PROFIT_COL,
        "memo",
        "result_tag",
    ]
    return df[column_order]


def split_by_sell_quantity(record):
    """
    한 번에 산 주식을 전부 다 팔지 않고 일부만 팔았을 때(부분매도), 한 줄로
    남겨두면 "매입수량"과 "매도수량"이 서로 달라서 헷갈리기 때문에 이 함수가
    두 줄로 나눠줍니다.

    1) "판 부분": 매입수량을 실제로 판 수량(매도수량)만큼으로 줄이고,
       매도 정보(매도일·매도가·수수료·세금)를 그대로 채운, 매매가 끝난 기록
    2) "안 판 부분": 남은 수량(매입수량-매도수량)만 매입수량으로 가지고,
       매도 정보는 전부 비운 채 계속 보유 중인 것으로 남는 새 기록

    매도수량이 0이면(아직 하나도 안 팜) 그대로 한 줄만 돌려줍니다.
    매도수량이 매입수량과 같거나 더 크면(전부 다 팔았거나, 잘못 입력된 값)
    쪼갤 필요가 없어서 한 줄만 돌려줍니다(매도수량이 더 큰 잘못된 값은
    호출하는 쪽에서 미리 걸러냅니다).
    """
    quantity = record.get("quantity") or 0
    sell_quantity = record.get("sell_quantity") or 0

    if sell_quantity <= 0 or sell_quantity >= quantity:
        return [record]

    sold_part = dict(record)
    sold_part["quantity"] = sell_quantity
    sold_part["sell_quantity"] = sell_quantity

    remaining_part = dict(record)
    remaining_part["quantity"] = quantity - sell_quantity
    remaining_part["sell_quantity"] = 0
    remaining_part["sell_date"] = None
    remaining_part["sell_price"] = 0.0
    remaining_part["fee"] = 0.0
    remaining_part["tax"] = 0.0
    remaining_part["memo"] = ""
    remaining_part["result_tag"] = "보류"

    return [sold_part, remaining_part]


def insert_trade(row):
    row = dict(row)
    row["user_id"] = user.id  # 어떤 사용자의 기록인지 표시해서 저장합니다.
    supabase.table("trades").insert(row).execute()


def _clean(value, default=None):
    """표에서 빈칸으로 남은 값(NaN)을 안전한 기본값으로 바꿔주는 함수"""
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return value


def _fetch_raw_trades():
    """
    지금 DB에 실제로 저장돼 있는 내용을 가공하지 않고 그대로 가져옵니다.
    "되돌리기" 기능에서 지우기 직전 상태를 백업해두는 용도로 씁니다.
    """
    response = supabase.table("trades").select("*").eq("user_id", user.id).execute()
    return response.data or []


def _save_undo_snapshot(action_label):
    """
    데이터를 지우기 직전에 호출해서, 지금 상태를 세션에 잠깐 기억해둡니다.
    (브라우저 탭을 닫거나 다른 페이지로 갔다 오면 사라집니다 - 실수로 저장/삭제한
    바로 다음에 되돌리는 용도입니다.)
    """
    st.session_state["undo_snapshot"] = _fetch_raw_trades()
    st.session_state["undo_label"] = action_label


def restore_undo_snapshot():
    """세션에 저장해둔 되돌리기 백업으로 복원합니다."""
    snapshot = st.session_state.get("undo_snapshot")
    if snapshot is None:
        return False
    supabase.table("trades").delete().eq("user_id", user.id).execute()
    # id는 DB가 새로 자동으로 매기게 두고, 나머지 값만 그대로 복원합니다.
    records = [{k: v for k, v in row.items() if k != "id"} for row in snapshot]
    if records:
        supabase.table("trades").insert(records).execute()
    st.session_state["undo_snapshot"] = None
    st.session_state["undo_label"] = None
    return True


def delete_all_trades():
    """로그인한 사용자 본인의 투자내역을 전부 삭제합니다(되돌리기용 백업을 먼저 남깁니다)."""
    _save_undo_snapshot("전체 삭제")
    supabase.table("trades").delete().eq("user_id", user.id).execute()


def replace_all_trades(df):
    """
    표에서 수정한 내용을 전부 반영합니다.
    로그인한 사용자 본인의 기존 데이터만 지우고, 표에 있는 내용으로 다시 채워 넣는 방식입니다
    (행을 수정하거나, 새 행을 추가하거나, 행을 삭제한 것 모두 이 방식으로 한 번에 반영됩니다).
    다른 사용자의 데이터는 건드리지 않습니다.
    "번호"·"손익" 칸은 화면에서만 보여주려고 계산한 값이라 저장 대상에서 제외합니다.
    부분매도(매도수량 < 매입수량)가 있는 행은 split_by_sell_quantity로 두 줄로 나눠 저장합니다.

    반환값: (성공 여부, 오류 메시지 또는 None)
    매도수량이 매입수량보다 큰 것처럼 잘못된 값이 하나라도 있으면, 기존 데이터를
    지우기 전에 먼저 전부 확인해서 아무것도 저장하지 않고 오류만 돌려줍니다
    (검증에 실패했는데 기존 데이터부터 지워버리면 안 되기 때문입니다).
    """
    records = []
    for _, row in df.iterrows():
        stock_name = str(_clean(row.get("stock_name"), "")).strip()
        if not stock_name:
            continue  # 종목명이 빈 줄은 저장하지 않습니다.

        quantity = int(_clean(row.get("quantity"), 0))
        sell_quantity = int(_clean(row.get("sell_quantity"), 0))
        if sell_quantity > quantity:
            return False, (
                f"'{stock_name}' 행의 매도수량({sell_quantity})이 "
                f"매입수량({quantity})보다 큽니다. 값을 확인해주세요."
            )

        base_record = {
            "user_id": user.id,
            "stock_name": stock_name,
            "stock_code": str(_clean(row.get("stock_code"), "")),
            "buy_date": str(_clean(row.get("buy_date"))) if _clean(row.get("buy_date")) else None,
            "buy_price": float(_clean(row.get("buy_price"), 0)),
            "quantity": quantity,
            "sell_date": str(_clean(row.get("sell_date"))) if _clean(row.get("sell_date")) else None,
            "sell_price": float(_clean(row.get("sell_price"), 0)),
            "sell_quantity": sell_quantity,
            "fee": float(_clean(row.get("fee"), 0)),
            "tax": float(_clean(row.get("tax"), 0)),
            "memo": str(_clean(row.get("memo"), "")),
            "result_tag": str(_clean(row.get("result_tag"), "")),
        }
        records.extend(split_by_sell_quantity(base_record))

    # 검증을 다 통과했을 때만, 지우기 직전 상태를 되돌리기용으로 남겨둡니다.
    _save_undo_snapshot("변경사항 저장 (표 수정)")

    supabase.table("trades").delete().eq("user_id", user.id).execute()
    if records:
        supabase.table("trades").insert(records).execute()
    return True, None


def build_holdings(df):
    """
    표에 있는 내용 중 아직 다 팔지 않고 보유 중인 부분(매입수량-매도수량 > 0)만
    종목별로 모아서, 보유수량·매입금액·평균매입가를 계산합니다.
    """
    work = df.copy()
    work["보유수량"] = work["quantity"].fillna(0) - work["sell_quantity"].fillna(0)
    work = work[work["보유수량"] > 0]
    if work.empty:
        return work

    work["매입금액_부분"] = work["보유수량"] * work["buy_price"].fillna(0)

    grouped = work.groupby(["stock_name", "stock_code"], as_index=False).agg(
        보유수량=("보유수량", "sum"), 매입금액=("매입금액_부분", "sum")
    )
    grouped["평균매입가"] = grouped["매입금액"] / grouped["보유수량"]
    return grouped


def _resolve_lookup_code(stock_name, stock_code):
    """
    종목코드 칸을 비워두고 저장한 경우, 현재가를 아예 못 가져오는 문제가
    있었습니다. 종목코드가 비어 있으면 재무데이터 조회 화면에서 쓰는
    corp_codes.csv(상장사 목록)에서 종목명으로 종목코드를 대신 찾아봅니다
    (get_financial_data.py의 find_stock_code 함수를 그대로 가져다 씀).
    이름이 정확히 일치하는 회사가 없으면 이름이 포함된 회사를 찾는데,
    이 경우 다른 회사가 잘못 걸릴 수도 있어서 화면에 "이름으로 자동 조회함"
    이라고 표시해 사용자가 확인할 수 있게 합니다.
    """
    code = str(stock_code or "").strip()
    if code:
        return code, False
    try:
        resolved = find_stock_code(stock_name)
    except Exception:
        resolved = None
    return (resolved, True) if resolved else ("", False)


def attach_current_prices(grouped):
    """
    보유 중인 종목들의 현재가를 네이버 금융에서 가져와 붙입니다.
    같은 종목코드를 중복해서 요청하지 않도록 먼저 종목코드 목록의 중복을
    없애고, 여러 종목의 현재가를 동시에(병렬로) 가져와서 기다리는 시간을
    줄입니다.
    """
    grouped = grouped.copy()
    resolved = grouped.apply(
        lambda r: _resolve_lookup_code(r["stock_name"], r["stock_code"]), axis=1
    )
    grouped["조회용_종목코드"] = [r[0] for r in resolved]
    grouped["이름으로_자동조회"] = [r[1] for r in resolved]

    codes = sorted({str(c).zfill(6) for c in grouped["조회용_종목코드"] if c})
    price_map = {}
    if codes:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(codes), 8)) as executor:
            price_map = dict(zip(codes, executor.map(get_current_price, codes)))

    def _lookup(code):
        if not code:
            return None
        return price_map.get(str(code).zfill(6))

    grouped["현재가"] = grouped["조회용_종목코드"].apply(_lookup)
    grouped["평가금액"] = grouped["보유수량"] * grouped["현재가"]
    grouped["평가손익"] = grouped["평가금액"] - grouped["매입금액"]
    return grouped


with st.form("trade_form", clear_on_submit=True):
    col1, col2 = st.columns(2)

    with col1:
        stock_name = st.text_input("종목명")
        stock_code = st.text_input("종목코드 (선택)")
        buy_date = st.date_input("매수일", value=date.today())
        buy_price = st.number_input("매수가", min_value=0.0, step=100.0)
        quantity = st.number_input("매입수량", min_value=0, step=1)

    with col2:
        sell_date = st.date_input("매도일", value=date.today())
        sell_price = st.number_input("매도가", min_value=0.0, step=100.0)
        sell_quantity = st.number_input("매도수량", min_value=0, step=1)
        fee = st.number_input("수수료", min_value=0.0, step=10.0)
        tax = st.number_input("세금", min_value=0.0, step=10.0)
        result_tag = st.selectbox("결과 태그", ["성공", "실패", "보류"])

    st.caption(
        "아직 팔지 않았다면 매도수량은 0으로 두세요. 전부 팔았다면 매입수량과 "
        "같은 숫자를, 일부만 팔았다면 판 수량만 입력하세요 - 나머지는 자동으로 "
        "별도 줄로 나뉘어 계속 보유 중인 것으로 남습니다."
    )
    memo = st.text_area("투자결과 분석 메모")
    submitted = st.form_submit_button("저장")

if submitted:
    if not stock_name.strip():
        st.error("종목명을 입력해주세요.")
    elif sell_quantity > quantity:
        st.error(f"매도수량({int(sell_quantity)})은 매입수량({int(quantity)})보다 클 수 없습니다.")
    else:
        base_record = {
            "stock_name": stock_name.strip(),
            "stock_code": stock_code.strip(),
            "buy_date": str(buy_date),
            "buy_price": buy_price,
            "quantity": int(quantity),
            "sell_date": str(sell_date),
            "sell_price": sell_price,
            "sell_quantity": int(sell_quantity),
            "fee": fee,
            "tax": tax,
            "memo": memo,
            "result_tag": result_tag,
        }
        parts = split_by_sell_quantity(base_record)
        for part in parts:
            insert_trade(part)

        if len(parts) == 2:
            st.success(
                f"{stock_name} 매매 기록이 저장되었습니다. "
                f"(판 {int(sell_quantity)}주 + 남은 {int(quantity - sell_quantity)}주, "
                "두 줄로 나눠 저장했습니다.)"
            )
        else:
            st.success(f"{stock_name} 매매 기록이 저장되었습니다.")

st.subheader("저장된 투자내역")
st.caption("표 안의 칸을 더블클릭하면 바로 수정할 수 있습니다. 행 왼쪽을 클릭해 선택한 뒤 휴지통 아이콘으로 삭제하거나, 표 맨 아래 빈 줄에 새로 입력해서 추가할 수도 있습니다.")
st.caption("가장 먼저 저장한 내용이 맨 위에 오도록 정렬되어 있고, 새로 추가한 줄은 맨 아래에 붙습니다.")
st.caption("'손익' 칸은 매도수량을 0보다 크게 입력하면 자동으로 계산됩니다((매도가-매수가)×매도수량-수수료-세금). 값을 고치고 '변경사항 저장'을 눌러야 다시 계산됩니다.")

trades_df = load_trades()

if trades_df.empty:
    st.info("아직 저장된 투자내역이 없습니다.")
else:
    edited_df = st.data_editor(
        trades_df,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",  # 행 추가/삭제 허용
        key="trades_editor",
        column_config={
            DISPLAY_NO_COL: st.column_config.NumberColumn(
                "번호",
                disabled=True,
                format="%d",
                help="지금 저장된 내용 순서대로 매겨지는 번호라 직접 수정할 수 없습니다.",
            ),
            "stock_name": st.column_config.TextColumn("종목명"),
            "stock_code": st.column_config.TextColumn("종목코드"),
            "buy_date": st.column_config.DateColumn("매수일"),
            "buy_price": st.column_config.NumberColumn("매수가", format="%,.0f"),
            "quantity": st.column_config.NumberColumn("매입수량", format="%,d"),
            "sell_date": st.column_config.DateColumn("매도일"),
            "sell_price": st.column_config.NumberColumn("매도가", format="%,.0f"),
            "sell_quantity": st.column_config.NumberColumn(
                "매도수량",
                format="%,d",
                help="일부만 팔았다면 판 수량만 입력하세요. '변경사항 저장'을 누르면 남은 수량은 자동으로 별도 줄로 나뉩니다.",
            ),
            "fee": st.column_config.NumberColumn("수수료", format="%,.0f"),
            "tax": st.column_config.NumberColumn("세금", format="%,.0f"),
            PROFIT_COL: st.column_config.NumberColumn(
                "손익",
                disabled=True,
                format="%,.0f",
                help="매도수량을 입력하면 자동으로 계산됩니다: (매도가-매수가)×매도수량-수수료-세금.",
            ),
            "memo": st.column_config.TextColumn("투자결과 분석 메모"),
            "result_tag": st.column_config.SelectboxColumn("결과 태그", options=["성공", "실패", "보류"]),
        },
    )

    col_save, col_delete_all = st.columns([1, 1])

    with col_save:
        if st.button("변경사항 저장", type="primary"):
            success, error_msg = replace_all_trades(edited_df)
            if success:
                st.success("수정 내용이 저장되었습니다.")
                st.rerun()
            else:
                st.error(error_msg)

    with col_delete_all:
        with st.popover("🗑️ 전체 삭제"):
            st.warning(
                "내 투자내역을 전부 삭제합니다. 삭제 직후에는 아래 '되돌리기'로 복구할 수 "
                "있지만, 그 뒤에 다른 저장을 하면 더는 복구할 수 없습니다."
            )
            confirm_delete_all = st.checkbox("정말로 전체 삭제하겠습니다", key="confirm_delete_all")
            if st.button("전체 삭제 실행", disabled=not confirm_delete_all):
                delete_all_trades()
                st.session_state.pop("confirm_delete_all", None)
                st.success("전체 삭제되었습니다.")
                st.rerun()

    if st.session_state.get("undo_snapshot") is not None:
        st.info(f"직전 작업: {st.session_state.get('undo_label', '')}. 잘못하셨다면 바로 되돌릴 수 있습니다.")
        if st.button("↩️ 바로 직전 상태로 되돌리기"):
            restore_undo_snapshot()
            st.success("직전 상태로 되돌렸습니다.")
            st.rerun()

    # ------------------------------------------------------------------
    # 손익 분석: 매도까지 끝난 내역만 모아서 연도별·연도월별로 손익을 집계합니다.
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("손익 분석")

    sell_df = trades_df[trades_df[PROFIT_COL].notna()].copy()

    if sell_df.empty:
        st.info("아직 매도까지 완료된 내역이 없어 손익 분석을 보여드릴 수 없습니다. 매도수량을 입력하고 저장하면 여기에 집계됩니다.")
    else:
        st.caption("매도수량이 0보다 큰(=조금이라도 매도한) 내역만 집계합니다.")

        total_profit = sell_df[PROFIT_COL].sum()
        total_color = PROFIT_COLOR if total_profit > 0 else (LOSS_COLOR if total_profit < 0 else "inherit")
        st.markdown(
            f"**총 손익 (전체 기간):** "
            f"<span style='color:{total_color}; font-size:1.4rem; font-weight:700'>{total_profit:,.0f}원</span>",
            unsafe_allow_html=True,
        )

        sell_df["연도"] = pd.to_datetime(sell_df["sell_date"]).dt.year
        sell_df["월"] = pd.to_datetime(sell_df["sell_date"]).dt.month

        col_year, col_month = st.columns(2)

        with col_year:
            st.caption("연도별 손익")
            yearly = (
                sell_df.groupby("연도")[PROFIT_COL]
                .agg(손익합계="sum", 매매건수="count")
                .reset_index()
                .sort_values("연도")
            )
            styled_year = yearly.style.format({"손익합계": "{:,.0f}원"})
            styled_year = _apply_profit_style(styled_year, ["손익합계"])
            st.dataframe(styled_year, hide_index=True, width="stretch")

        with col_month:
            st.caption("연도·월별 손익")
            monthly = (
                sell_df.groupby(["연도", "월"])[PROFIT_COL]
                .agg(손익합계="sum", 매매건수="count")
                .reset_index()
                .sort_values(["연도", "월"])
            )
            styled_month = monthly.style.format({"손익합계": "{:,.0f}원"})
            styled_month = _apply_profit_style(styled_month, ["손익합계"])
            st.dataframe(styled_month, hide_index=True, width="stretch")

    # ------------------------------------------------------------------
    # 보유 현황: 아직 팔지 않은 수량을 현재가와 연동해서 평가금액을 보여줍니다.
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("보유 현황 (현재가 반영)")
    st.caption(
        "네이버 금융의 최근 종가를 기준으로 계산합니다(장중 실시간 가격이 아니라 "
        "직전 거래일 종가일 수 있습니다). 종목코드를 입력하지 않은 종목은 현재가를 가져올 수 없습니다."
    )

    holdings = build_holdings(trades_df)

    if holdings.empty:
        st.info("현재 보유 중인 종목이 없습니다.")
    else:
        with st.spinner("현재가를 불러오는 중입니다..."):
            holdings = attach_current_prices(holdings)

        total_cost = holdings["매입금액"].sum()
        has_price = holdings["평가금액"].notna().any()
        total_value = holdings["평가금액"].dropna().sum() if has_price else None

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("총 매입금액", f"{total_cost:,.0f}원")
        if has_price:
            col_b.metric("총 평가금액", f"{total_value:,.0f}원")
            total_pl = total_value - total_cost
            pl_color = PROFIT_COLOR if total_pl > 0 else (LOSS_COLOR if total_pl < 0 else "inherit")
            col_c.markdown(
                f"총 평가손익<br><span style='color:{pl_color}; font-size:1.5rem; font-weight:700'>{total_pl:,.0f}원</span>",
                unsafe_allow_html=True,
            )
        else:
            col_b.metric("총 평가금액", "정보 없음")

        display_holdings = holdings.drop(columns=["조회용_종목코드", "이름으로_자동조회"]).rename(
            columns={"stock_name": "종목명", "stock_code": "종목코드"}
        )
        styled_holdings = display_holdings.style.format(
            {
                "보유수량": "{:,.0f}",
                "평균매입가": "{:,.0f}원",
                "매입금액": "{:,.0f}원",
                "현재가": lambda v: "정보 없음" if pd.isna(v) else f"{v:,.0f}원",
                "평가금액": lambda v: "정보 없음" if pd.isna(v) else f"{v:,.0f}원",
                "평가손익": lambda v: "-" if pd.isna(v) else f"{v:,.0f}원",
            }
        )
        styled_holdings = _apply_profit_style(styled_holdings, ["평가손익"])
        st.dataframe(styled_holdings, hide_index=True, width="stretch")

        auto_matched = holdings[holdings["이름으로_자동조회"] & holdings["조회용_종목코드"].astype(bool)]
        if not auto_matched.empty:
            matched_text = ", ".join(
                f"{row.stock_name}({row.조회용_종목코드})" for row in auto_matched.itertuples()
            )
            st.caption(
                "종목코드를 입력하지 않아서, 이름으로 자동 조회한 종목코드로 현재가를 가져왔습니다: "
                f"{matched_text}. 이름이 비슷한 다른 회사가 잘못 걸렸을 수 있으니, 정확하게 하려면 "
                "위 표(저장된 투자내역)에서 종목코드를 직접 입력해주세요."
            )

        missing = holdings[holdings["현재가"].isna()]
        if not missing.empty:
            st.caption("현재가를 못 가져온 종목: " + ", ".join(missing["stock_name"].tolist()) + " (종목코드를 확인해주세요.)")
