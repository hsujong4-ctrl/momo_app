import base64
import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from curl_cffi import requests as cf_requests  # 模擬 Chrome 的 TLS 指紋

st.set_page_config(page_title="MOMO 商品價格分析", layout="wide")
st.title("MOMO 商品搜尋與價格分析")

API_URL = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
HOME_URL = "https://www.momoshop.com.tw/"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/",
}

FONT_PATH = Path("fonts/TaipeiSansTCBeta-Regular.ttf")
FONT_URL = "https://drive.google.com/uc?id=1eGAsTN1HBpJAkeVM57_C7ccp7hbgSz3_&export=download"
FONT_FAMILY = "Taipei Sans TC Beta"
CHART_FONT = f"{FONT_FAMILY}, Microsoft JhengHei, PingFang TC, Noto Sans TC, sans-serif"


# ---------- 中文字型（取代 !wget） ----------
@st.cache_resource(show_spinner="載入中文字型...")
def load_font_b64() -> str | None:
    """下載字型到 fonts/ 資料夾（若已存在則直接讀取），回傳 base64 字串。"""
    if not FONT_PATH.exists():
        try:
            FONT_PATH.parent.mkdir(parents=True, exist_ok=True)
            resp = cf_requests.get(FONT_URL, impersonate="chrome", timeout=60)
            if resp.status_code != 200:
                return None
            # Google Drive 大檔可能回傳 HTML 確認頁，這時不能當字型使用
            if b"<html" in resp.content[:200].lower():
                return None
            FONT_PATH.write_bytes(resp.content)
        except Exception:
            return None
    return base64.b64encode(FONT_PATH.read_bytes()).decode()


# ---------- 爬取 MOMO ----------
def build_payload(keyword: str, page: int) -> dict:
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "searchValue": keyword,
            "searchType": "1",
            "cateLevel": "-1",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "showType": "chessboardType",
            "isFuzzy": "0",
            "rtnCateDatainfo": {
                "cateCode": "",
                "cateLv": "-1",
                "keyword": keyword,
                "curPage": str(page),  # 與外層一致
                "historyDoPush": "false",
                "timestamp": int(time.time() * 1000),  # 用當下時間
            },
            "flag": 2018,
            "serviceCode": "MT01",
            "addressSearchData": {},
        },
    }


def create_session():
    session = cf_requests.Session(impersonate="chrome")
    session.get(HOME_URL, headers=HEADERS, timeout=30)  # 先取得 cookie
    return session


def scrape_momo(keyword: str, pages: int, delay: float) -> pd.DataFrame:
    rows = []
    session = create_session()
    progress = st.progress(0.0, text="準備爬取...")
    for page in range(1, pages + 1):
        resp = session.post(
            API_URL, headers=HEADERS, json=build_payload(keyword, page), timeout=30
        )
        if resp.status_code != 200:
            progress.empty()
            raise RuntimeError(f"HTTP {resp.status_code}：{resp.text[:200]}")
        products = resp.json().get("rtnSearchData", {}).get("goodsInfoList", []) or []
        rows.extend(
            {"品名": p.get("goodsName", ""), "價格": p.get("goodsPrice", "")}
            for p in products
        )
        progress.progress(page / pages, text=f"已完成第 {page}/{pages} 頁")
        if page < pages and delay > 0:
            time.sleep(delay)  # 每頁間隔，避免請求過於頻繁
    progress.empty()
    return pd.DataFrame(rows, columns=["品名", "價格"])


def clean_price(series: pd.Series) -> pd.Series:
    """去除 $、逗號等非數字字元後轉為數值（與原程式相同的處理方式）。"""
    digits = series.astype(str).str.replace(r"[^\d]", "", regex=True)
    return pd.to_numeric(digits, errors="coerce")


# ---------- 側邊欄 ----------
with st.sidebar:
    st.header("爬取設定")
    delay = st.slider(
        "每頁間隔秒數", min_value=0, max_value=10, value=3,
        help="間隔過短可能導致請求被 MOMO 擋下",
    )

# ---------- 搜尋表單 ----------
with st.form("search_form"):
    keyword = st.text_input("產品名稱", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=50, value=1, step=1)
    submitted = st.form_submit_button("開始爬取")

if submitted:
    if not keyword.strip():
        st.warning("請輸入產品名稱")
    else:
        try:
            df_raw = scrape_momo(keyword.strip(), int(pages), delay)
            st.session_state["raw"] = df_raw
            st.session_state["keyword"] = keyword.strip()
        except Exception as e:
            st.error(f"爬取失敗：{e}")

# ---------- 字型注入（讓 plotly 圖表使用中文字型） ----------
font_b64 = load_font_b64()
if font_b64:
    st.markdown(
        f"<style>@font-face {{font-family: '{FONT_FAMILY}';"
        f"src: url(data:font/ttf;base64,{font_b64}) format('truetype');}}</style>",
        unsafe_allow_html=True,
    )

# ---------- 顯示結果 ----------
df_raw = st.session_state.get("raw")
if df_raw is None:
    st.info("請輸入產品名稱與頁數，然後按「開始爬取」。")
    st.stop()

if df_raw.empty:
    st.warning("查無資料，請換個關鍵字試試。")
    st.stop()

keyword_shown = st.session_state.get("keyword", "")
st.subheader(f"「{keyword_shown}」搜尋結果")

data = df_raw.copy()
data["價格"] = clean_price(data["價格"])
data = data.dropna(subset=["價格"]).reset_index(drop=True)
data["價格"] = data["價格"].astype(int)
data["排名"] = data.index + 1

if data.empty:
    st.warning("價格欄位無法解析，請確認 API 回傳格式是否變動。")
    st.stop()

# ---------- 摘要 ----------
c1, c2, c3, c4 = st.columns(4)
c1.metric("商品筆數", f"{len(data):,}")
c2.metric("平均價格", f"{data['價格'].mean():,.0f}")
c3.metric("最高價格", f"{data['價格'].max():,.0f}")
c4.metric("最低價格", f"{data['價格'].min():,.0f}")

# ---------- 折線圖 ----------
st.markdown("### 價格折線圖（依搜尋排序）")
if len(data) > 1:
    top_n = st.slider("顯示前 N 筆", min_value=1, max_value=len(data),
                      value=min(70, len(data)))
else:
    top_n = len(data)
line_df = data.head(top_n)

mean_price = data["價格"].mean()
fig_line = px.line(
    line_df, x="排名", y="價格", markers=True,
    labels={"排名": "排名", "價格": "售價"},
    title=f"{keyword_shown} 售價走勢（前 {top_n} 筆）",
)
fig_line.add_hline(
    y=mean_price, line_dash="dash", line_color="red",
    annotation_text=f"平均 {mean_price:,.0f}",
)
fig_line.update_layout(font_family=CHART_FONT, height=450)
st.plotly_chart(fig_line, use_container_width=True)

# ---------- 價格區間（圓餅圖與旭日圖共用） ----------
lo, hi = data["價格"].min(), data["價格"].max()
if lo == hi:
    hi = lo + 1
edges = np.linspace(lo, hi, 6)
labels = [f"{edges[i]:,.0f}–{edges[i + 1]:,.0f}" for i in range(5)]
data["價格區間"] = pd.cut(
    data["價格"], bins=edges, labels=labels, include_lowest=True
).astype(str)
data["短品名"] = data["品名"].astype(str).str.slice(0, 15)

col_pie, col_sun = st.columns(2)

with col_pie:
    st.markdown("### 價格區間分布（圓餅圖）")
    counts = data["價格區間"].value_counts().reset_index()
    counts.columns = ["價格區間", "數量"]
    fig_pie = px.pie(
        counts, names="價格區間", values="數量",
        title="各價格區間商品數量",
    )
    fig_pie.update_traces(textinfo="percent+label")
    fig_pie.update_layout(font_family=CHART_FONT, height=500)
    st.plotly_chart(fig_pie, use_container_width=True)

with col_sun:
    st.markdown("### 價格區間與商品（旭日圖）")
    fig_sun = px.sunburst(
        data, path=["價格區間", "短品名"],
        title="價格區間 → 商品名稱",
    )
    fig_sun.update_layout(font_family=CHART_FONT, height=500)
    st.plotly_chart(fig_sun, use_container_width=True)

# ---------- 資料表與下載 ----------
st.markdown("### 資料表")
st.dataframe(data[["排名", "品名", "價格", "價格區間"]], height=400)

st.download_button(
    label="下載 CSV（取代原程式的 to_csv）",
    data=data[["品名", "價格"]].to_csv(index=False).encode("utf-8-sig"),
    file_name=f"MOMO_{keyword_shown}.csv",
    mime="text/csv",
)
