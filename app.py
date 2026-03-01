import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import plotly.graph_objects as go
import pandas as pd

# ページの設定
st.set_page_config(page_title="企業バリュー検索アプリ", page_icon="🏢", layout="wide")

# ==========================================
# ★ セッションステートの初期化
# ==========================================
if 'selected_page' not in st.session_state:
    st.session_state.selected_page = "🔍 個別銘柄を検索"
if 'search_code' not in st.session_state:
    st.session_state.search_code = ""
if 'auto_search' not in st.session_state:
    st.session_state.auto_search = False

# ==========================================
# ★設定エリア: オリジナル指標「P/與」の倍率定義
# ==========================================
MULTIPLIERS = {
    "流動_現金及び預金": 1, "流動_受取手形": 0.8, "流動_売掛金": 0.8, "流動_契約資産": 0.8,
    "流動_電子記録債権": 0.8, "流動_受取手形・売掛金(合算)": 0.8, "流動_有価証券": 1,
    "流動_棚卸資産": 0.5, "流動_前払費用": 0.8, "流動_未収入金": 0.8, "流動_未収消費税等": 0.8,
    "流動_短期貸付金": 0.8, "流動_リース債権": 0.8, "流動_貸倒引当金": 1, "流動_その他流動資産": 0.15,
    "有形_建物・構築物": 0.15, "有形_機械・運搬具": 0.15, "有形_土地": 0.15, "有形_建設仮勘定": 0.15,
    "有形_リース資産": 0.15, "有形_賃貸用資産": 0.15, "有形_工具器具備品": 0.15, "有形_その他有形固定資産": 0.15,
    "無形_ソフトウエア": 0.15, "無形_のれん": 0.15, "無形_借地権": 0.15, "無形_その他無形固定資産": 0.15,
    "投資_投資有価証券": 1, "投資_関係会社株式": 0.15, "投資_投資不動産": 0.15, "投資_長期貸付金": 0.15,
    "投資_差入保証金": 0.15, "投資_退職給付資産": 0.15, "投資_繰延税金資産": 0.15, "投資_貸倒引当金": 1,
    "投資_その他固定資産": 0.15, "純資_非支配株主持分": -1, "★負債合計": -1
}

# ==========================================
# 1. Firebaseの接続設定
# ==========================================
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        if "firebase" in st.secrets:
            cert_dict = dict(st.secrets["firebase"])
            cred = credentials.Certificate(cert_dict)
        else:
            cred = credentials.Certificate('firebase_key.json')
            
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = init_firebase()

# ==========================================
# ★全データの一括取得＆キャッシュ（暗記）機能
# ==========================================
@st.cache_data(ttl=21600, show_spinner="データベースから全銘柄をダウンロード中...（初回のみ数秒かかります）")
def get_cached_all_companies():
    docs = db.collection('companies').stream()
    result_dict = {}
    for doc in docs:
        result_dict[doc.id] = doc.to_dict()
    return result_dict

# ==========================================
# 2. 独自ロジック群
# ==========================================
def calculate_p_yo(data):
    raw_adj_bs_asset = 0
    for key, multiplier in MULTIPLIERS.items():
        val = data.get(key, 0)
        raw_adj_bs_asset += val * multiplier
        
    sec_profit = data.get('有価証券_含み益_億', 0)
    tax_deduction = sec_profit * 0.3
    adj_bs_asset = raw_adj_bs_asset - tax_deduction
        
    market_val = data.get('不動産_時価_億', 0)
    book_val = data.get('不動産_簿価_億', 0)
    adj_re_val = 0
    if market_val > 0:
        adj_re_val = market_val - (book_val * 0.15) - ((market_val - book_val) * 0.3)
        
    market_cap = data.get('時価総額_億', 0)
    bargain_degree = 0
    if market_cap > 0:
        bargain_degree = (adj_bs_asset + adj_re_val) / market_cap
        
    p_yo = 0
    if bargain_degree > 0:
        p_yo = 1 / bargain_degree
        
    return {
        "倍率計算のみのBS": round(raw_adj_bs_asset, 2),
        "有価証券_税金控除額": round(tax_deduction, 2),
        "調整済み資産額_BS": round(adj_bs_asset, 2),
        "調整済み不動産額": round(adj_re_val, 2),
        "実質純資産": round(adj_bs_asset + adj_re_val, 2),
        "お買い得度": round(bargain_degree, 2),
        "P_與": round(p_yo, 2) if p_yo > 0 else "-"
    }

def calculate_value_score(data, p_yo_data):
    score = 0
    messages = []
    p_yo = p_yo_data.get("P_與", "-")
    pbr = data.get('PBR', 0)
    roe = data.get('ROE_pct', 0)
    real_estate_profit = data.get('不動産_含み益_億', 0)
    sec_profit = data.get('有価証券_含み益_億', 0)
    market_cap = data.get('時価総額_億', 0)

    # ① P/與 (Max 40点)
    score_pyo = 0
    if isinstance(p_yo, (int, float)) and p_yo >= 0:
        if p_yo <= 0.5:
            score_pyo = 40
        elif p_yo < 1.0:
            score_pyo = 40 - ((p_yo - 0.5) / 0.5) * 40
        score += score_pyo
        
        if p_yo <= 0.5:
            messages.append(f"🔥 【超絶割安】実質PBR(P/與)が0.5以下 (+{int(score_pyo)}点)")
        elif p_yo < 1.0:
            messages.append(f"✅ 【割安】実質PBR(P/與)が1.0未満 (+{int(score_pyo)}点)")

    # ② 表面PBR (Max 20点)
    score_pbr = 0
    if isinstance(pbr, (int, float)) and pbr >= 0:
        if pbr <= 0.5:
            score_pbr = 20
        elif pbr < 1.0:
            score_pbr = 20 - ((pbr - 0.5) / 0.5) * 20
        score += score_pbr
        
        if 0 <= pbr <= 0.5:
            messages.append(f"✅ 表面上のPBRも0.5倍以下 (+{int(score_pbr)}点)")

    # ③ 含み益インパクト (Max 30点)
    score_hidden = 0
    total_hidden_profit = real_estate_profit + sec_profit
    if market_cap > 0 and total_hidden_profit > 0:
        hidden_ratio = total_hidden_profit / market_cap
        score_hidden = min(30.0, hidden_ratio * 30.0)
        score += score_hidden
        
        if hidden_ratio >= 1.0:
            messages.append(f"🔥 含み益({round(total_hidden_profit, 1)}億)が時価総額以上！ (+{int(score_hidden)}点)")
        elif hidden_ratio >= 0.3:
            messages.append(f"✅ 時価総額に対して30%以上の含み益あり (+{int(score_hidden)}点)")

    # ④ ROE (Max 10点)
    score_roe = 0
    if isinstance(roe, (int, float)) and roe > 0:
        if roe >= 8.0:
            score_roe = 10.0
        else:
            score_roe = (roe / 8.0) * 10.0
        score += score_roe
        
        if roe >= 8:
            messages.append(f"✅ ROE8%以上で稼ぐ力あり (+{int(score_roe)}点)")

    return int(score), messages

def check_bs_anomaly(data):
    anomalies = []
    total_assets = data.get('★資産合計', 0)
    if total_assets <= 0: return anomalies
        
    threshold = total_assets * 0.05
    others_keys = ["流動_その他流動資産", "有形_その他有形固定資産", "無形_その他無形固定資産", 
                   "投資_その他固定資産", "流負_その他流動負債", "固負_その他固定負債", "純資_その他純資産"]
    
    for key in others_keys:
        val = data.get(key, 0)
        if val < -threshold:
            anomalies.append(f"【{key}】が過剰なマイナス ({val}億円) です。他の項目に過大な値が計上されている可能性があります。")
            
    return anomalies

def calculate_target_price(data, current_score, p_yo_data):
    current_price = data.get('株価', 0)
    if current_price <= 0:
        return "✖️データなし", None, None
        
    if current_score >= 70:
        return "✅購入水準", current_price, 0.0

    sim_data_min = data.copy()
    sim_data_min['時価総額_億'] = data.get('時価総額_億', 0) * 0.0001
    sim_data_min['PBR'] = data.get('PBR', 0) * 0.0001
    sim_pyo_min = calculate_p_yo(sim_data_min)
    min_score, _ = calculate_value_score(sim_data_min, sim_pyo_min)
    
    if min_score < 70:
        return "❌購入非推奨", None, None

    low = 0.0001
    high = 1.0
    best_r = None
    
    for _ in range(20):
        mid = (low + high) / 2
        sim_data = data.copy()
        sim_data['時価総額_億'] = data.get('時価総額_億', 0) * mid
        sim_data['PBR'] = data.get('PBR', 0) * mid
        sim_pyo = calculate_p_yo(sim_data)
        score, _ = calculate_value_score(sim_data, sim_pyo)
        
        if score >= 70:
            best_r = mid
            low = mid
        else:
            high = mid

    if best_r is not None:
        target_price = current_price * best_r
        drop_rate = (1 - best_r) * 100
        return "⏳下落待ち", int(target_price), round(drop_rate, 1)
    else:
        return "❌購入非推奨", None, None

def show_company_details(code, data, p_yo_data):
    st.header(f"[{code}] {data.get('★企業名', '名称不明')}")
    st.caption(f"業種: {data.get('★業種', '-')} | 市場: {data.get('★市場区分', '-')} | 最終更新: {data.get('データ最終更新日', '')}")
    
    val_score, val_msgs = calculate_value_score(data, p_yo_data)
    
    if val_score >= 70: st.success(f"### 💎 総合バリュースコア: {val_score} / 100点 (超お宝銘柄の可能性！)")
    elif val_score >= 40: st.info(f"### ⭐ 総合バリュースコア: {val_score} / 100点 (割安圏内)")
    else: st.warning(f"### 総合バリュースコア: {val_score} / 100点")
        
    if val_msgs: st.markdown("\n".join([f"- {msg}" for msg in val_msgs]))
    
    status, target_price, drop_rate = calculate_target_price(data, val_score, p_yo_data)
    
    if status == "❌購入非推奨":
        st.error("💡 **購入目安株価:** 現在の財務状態（ROE不足や含み資産がない等）では、**株価がどれだけ下がっても70点に到達しません。**（手を出してはいけない「バリュートラップ」の可能性があります）")
    elif status == "⏳下落待ち":
        st.info(f"💡 **購入目安株価:** 約 **{target_price} 円** まで下がるとスコアが70点に到達します！（現在価格から **-{drop_rate}%** の下落待ち）")
    elif status == "✅購入水準":
        st.success("💡 **購入判定:** 既に70点以上の **✅購入水準** に達しています！")

    total_assets = data.get('★資産合計', 0)
    if total_assets <= 0:
        st.warning("⚠️ **B/Sデータが取得できていません。** 各種指標の計算が不完全な可能性があります。")
    else:
        anomalies = check_bs_anomaly(data)
        if anomalies:
            st.warning("⚠️ **【注意】B/Sデータにノイズが含まれている可能性があります**\n\n" + "\n".join([f"- {msg}" for msg in anomalies]) + "\n\n*※P/與の算出結果が実態と大きくズレている可能性があります。*")
        
    st.divider()

    tab1, tab2, tab3 = st.tabs(["📊 サマリー", "🥧 財務グラフ", "📋 詳細データ一覧"])

    with tab1:
        st.subheader("💡 重要指標")
        st.markdown("#### 🔥 オリジナル評価指標")
        p_yo_val = p_yo_data['P_與']
        
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("P/與 (実質PBR)", f"{p_yo_val} 倍" if p_yo_val != "-" else "-", delta="超割安！" if isinstance(p_yo_val, (int, float)) and p_yo_val < 0.8 else None, delta_color="inverse")
        mc2.metric("実質 純資産 (換金価値)", f"{p_yo_data['実質純資産']} 億円")
        mc3.metric("時価総額 (買収価格)", f"{data.get('時価総額_億', 0)} 億円")
        
        st.divider()
        st.markdown("#### 基本財務指標")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("現在の株価", f"{data.get('株価', 0)} 円")
        c2.metric("表面PBR", f"{data.get('PBR', 0)} 倍")
        
        re_profit = data.get('不動産_含み益_億', 0)
        sec_profit = data.get('有価証券_含み益_億', 0)
        c3.metric("🏢 不動産 含み益", f"{re_profit} 億円")
        c4.metric("📈 有価証券 含み益", f"{sec_profit} 億円")

    with tab2:
        st.subheader("⚖️ 貸借対照表 (B/S) バランス")
        assets = data.get('★資産合計', 0)
        liabilities = data.get('★負債合計', 0)
        net_assets = data.get('★純資産合計', 0)
        
        if assets > 0:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=['資産 (Assets)'], y=[assets], name='総資産', marker_color='#3498db', width=0.4))
            fig.add_trace(go.Bar(x=['負債・純資産 (Liabilities)'], y=[liabilities], name='負債', marker_color='#e74c3c', width=0.4))
            fig.add_trace(go.Bar(x=['負債・純資産 (Liabilities)'], y=[net_assets], name='純資産', marker_color='#2ecc71', width=0.4))
            fig.update_layout(barmode='stack', title_text=f"B/S 構造グラフ (単位: 億円)", height=500, plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("B/Sデータが取得されていないため、グラフを描画できません。")

    with tab3:
        st.subheader("🔍 P/與 計算プロセス")
        st.markdown("独自の掛け目によるB/S調整と、有価証券の含み益に対する潜在的な税金（30%）控除を行っています。")
        calc_steps = {
            "① B/S資産額 (倍率計算のみ)": f"{p_yo_data.get('倍率計算のみのBS', 0)} 億円",
            "② 有価証券 含み益 (税金控除)": f"▲ {p_yo_data.get('有価証券_税金控除額', 0)} 億円",
            "③ 調整済 B/S資産 (①-②)": f"{p_yo_data.get('調整済み資産額_BS', 0)} 億円",
            "④ 調整済 不動産": f"{p_yo_data.get('調整済み不動産額', 0)} 億円",
            "⑤ 実質純資産 (③+④)": f"{p_yo_data.get('実質純資産', 0)} 億円",
            "⑥ お買い得度 (⑤÷時価総額)": str(p_yo_data.get('お買い得度', 0)),
            "🎯 最終 P/與 (1÷⑥)": f"{p_yo_data.get('P_與', '-')} 倍"
        }
        st.table(calc_steps)
        st.divider()
        
        st.subheader("📋 ご指定の全指標データ一覧")
        col_l, col_r = st.columns(2)
        
        with col_l:
            st.markdown("**■ バリュー・株価・資産指標**")
            st.table({
                "P/與": str(p_yo_data.get('P_與', '-')),
                "PBR (倍)": str(data.get('PBR', 0)),
                "PER (倍)": str(data.get('PER', 0)),
                "4年平均PER_赤字除 (倍)": str(data.get('4年平均PER_赤字除', 0)),
                "株価 (円)": str(data.get('株価', 0)),
                "時価総額 (億)": str(data.get('時価総額_億', 0)),
                "調整済み資産 (億)": str(p_yo_data.get('調整済み資産額_BS', 0)),
                "調整済み不動産 (億)": str(p_yo_data.get('調整済み不動産額', 0)),
                "有価証券含み益 (億)": str(data.get('有価証券_含み益_億', 0)),
                "純資産 (億)": str(data.get('純資産_億', 0)),
                "10年平均時価総額 (億)": str(data.get('10年平均時価総額_億', 0)),
                "EPS (円)": str(data.get('EPS', 0)),
                "ROE (%)": str(data.get('ROE_pct', 0))
            })

        with col_r:
            st.markdown("**■ 還元・業績推移指標**")
            st.table({
                "配当利回り (%)": str(data.get('配当利回り_pct', 0)),
                "配当性向 (%)": str(data.get('配当性向_pct', 0)),
                "4年自社株買い利回り (%)": str(data.get('4年自社株買い利回り_pct', 0)),
                "4年平均還元利回り (%)": str(data.get('4年平均還元利回り_pct', 0)),
                "4年平均自社株買い (億)": str(data.get('4年平均自社株買い_億', 0)),
                "4年平均総還元額 (億)": str(data.get('4年平均総還元額_億', 0)),
                "4年自社株買い比率 (%)": str(data.get('4年自社株買い比率_pct', 0)),
                "10年増配率 (%)": str(data.get('10年増配率_pct', 0)),
                "10年減配率 (%)": str(data.get('10年減配率_pct', 0)),
                "4年最低営業利益 (億)": str(data.get('4年最低営業利益_億', 0)),
                "4年最低経常利益 (億)": str(data.get('4年最低経常利益_億', 0)),
                "4年赤字率 (%)": str(data.get('4年赤字率_pct', 0))
            })

        with st.expander("すべての生データをJSONで確認する（開発・確認用）"):
            st.json(data)

# ==========================================
# 3. メニュー（サイドバー）設定
# ==========================================
st.sidebar.title("メニュー")
st.sidebar.markdown("ご覧になりたい機能を選択してください。")

def update_page():
    st.session_state.selected_page = st.session_state.page_radio

st.sidebar.radio(
    " ", 
    ["🔍 個別銘柄を検索", "📋 全銘柄一覧（スクリーニング）"], 
    key="page_radio",
    index=0 if st.session_state.selected_page == "🔍 個別銘柄を検索" else 1,
    on_change=update_page
)

st.sidebar.divider()

# ★修正: 全てのチェックボックスの初期値を「True」に変更
allowed_statuses = []
if st.session_state.selected_page == "📋 全銘柄一覧（スクリーニング）":
    st.sidebar.markdown("### 🎯 絞り込みフィルター")
    st.sidebar.caption("チェックを入れた判定の銘柄だけを表示します。")
    show_buy = st.sidebar.checkbox("✅ 購入水準", value=True)
    show_wait = st.sidebar.checkbox("⏳ 下落待ち", value=True)
    show_no_buy = st.sidebar.checkbox("❌ 購入非推奨", value=True)
    show_no_data = st.sidebar.checkbox("✖️ データなし", value=True)
    
    if show_buy: allowed_statuses.append("✅購入水準")
    if show_wait: allowed_statuses.append("⏳下落待ち")
    if show_no_buy: allowed_statuses.append("❌購入非推奨")
    if show_no_data: allowed_statuses.append("✖️データなし")
    
    st.sidebar.divider()

st.sidebar.caption("データソース: JPX / Yahoo Finance / EDINET")

# ==========================================
# 4. ページごとの表示処理
# ==========================================

if st.session_state.selected_page == "🔍 個別銘柄を検索":
    st.title("🏢 企業バリュー検索アプリ")
    
    col_search, _ = st.columns([1, 2])
    with col_search:
        input_code = st.text_input("証券コード（4桁）を入力", st.session_state.search_code, max_chars=4)
        search_btn = st.button("検索する", type="primary", use_container_width=True)

    execute_search = search_btn or st.session_state.auto_search
    
    if execute_search and input_code:
        st.session_state.search_code = input_code
        st.session_state.auto_search = False
        
        with st.spinner('データベースから取得中...'):
            cached_data = get_cached_all_companies()
            
        if input_code in cached_data:
            data = cached_data[input_code]
            p_yo_data = calculate_p_yo(data)
            show_company_details(input_code, data, p_yo_data)
        else:
            st.error(f"証券コード「{input_code}」のデータは存在しません。")

elif st.session_state.selected_page == "📋 全銘柄一覧（スクリーニング）":
    st.title("📋 全銘柄一覧 (スクリーニング)")
    st.markdown("Firebaseに保存されている全銘柄の全指標を一覧表示します。")

    try:
        cached_data_dict = get_cached_all_companies()
        
        all_data_list = []
        raw_data_dict = {} 
        
        for code, data in cached_data_dict.items():
            p_yo_data = calculate_p_yo(data)
            score, _ = calculate_value_score(data, p_yo_data)
            
            raw_data_dict[code] = {"data": data, "p_yo": p_yo_data}
            
            p_yo_val = p_yo_data.get('P_與', None)
            if p_yo_val == "-": p_yo_val = None
            
            total_assets = data.get('★資産合計', 0)
            if total_assets <= 0:
                alert_status = "✖️データなし"
            else:
                anomalies = check_bs_anomaly(data)
                alert_status = "⚠️要確認" if anomalies else "✅正常"

            status, target_price, drop_rate = calculate_target_price(data, score, p_yo_data)

            all_data_list.append({
                "コード": code,
                "企業名": data.get('★企業名', '名称不明'),
                "購入判定": status,
                "P/與": p_yo_val,
                "バリュースコア": score,
                "70点_目安株価(円)": target_price, 
                "70点_下落待ち(%)": drop_rate,
                "データ状態": alert_status,
                "PBR(倍)": data.get('PBR', 0),
                "PER(倍)": data.get('PER', 0),
                "配当利回り(%)": data.get('配当利回り_pct', 0),
                "ROE(%)": data.get('ROE_pct', 0),
                "時価総額(億)": data.get('時価総額_億', 0),
                "調整済み資産(億)": p_yo_data.get('調整済み資産額_BS', 0),
                "調整済み不動産(億)": p_yo_data.get('調整済み不動産額', 0),
                "有価証券含み益(億)": data.get('有価証券_含み益_億', 0),
                "株価(円)": data.get('株価', 0),
                "EPS": data.get('EPS', 0),
                "4年平均PER(赤字除)": data.get('4年平均PER_赤字除', 0),
                "配当性向(%)": data.get('配当性向_pct', 0),
                "4年平均還元利回り(%)": data.get('4年平均還元利回り_pct', 0),
                "4年自社株買い利回り(%)": data.get('4年自社株買い利回り_pct', 0),
                "4年平均自社株買い(億)": data.get('4年平均自社株買い_億', 0),
                "4年平均総還元額(億)": data.get('4年平均総還元額_億', 0),
                "4年自社株買い比率(%)": data.get('4年自社株買い比率_pct', 0),
                "10年増配率(%)": data.get('10年増配率_pct', 0),
                "10年減配率(%)": data.get('10年減配率_pct', 0),
                "4年最低営業利益(億)": data.get('4年最低営業利益_億', 0),
                "4年最低経常利益(億)": data.get('4年最低経常利益_億', 0),
                "4年赤字率(%)": data.get('4年赤字率_pct', 0),
                "純資産(億)": data.get('純資産_億', 0),
                "10年平均時価総額(億)": data.get('10年平均時価総額_億', 0),
                "市場": data.get('★市場区分', '-'),
                "業種": data.get('★業種', '-')
            })
            
        if all_data_list:
            df = pd.DataFrame(all_data_list)
            
            df = df[df['購入判定'].isin(allowed_statuses)]
            
            if df.empty:
                st.warning("⚠️ 条件に一致する銘柄がありません。左のメニューからチェックボックスを入れてください。")
            else:
                df.set_index(['コード', '企業名'], inplace=True)
                
                st.success(f"条件に一致する **{len(df)}** 件の企業データを抽出しました！")
                
                # ★修正: 操作Tipsにサイドバーの絞り込み機能の案内を追加し、箇条書きで整理
                st.info("💡 **操作Tips:**\n"
                        "- 表の左端にある **チェックボックスを1回入れる** だけで、すぐ下にその銘柄の詳細データがパッと開きます！\n"
                        "- 画面左側の **メニュー（サイドバー）のチェックボックス** を切り替えることで、見たい判定の銘柄だけに表を絞り込むことができます。")
                
                event = st.dataframe(
                    df, 
                    use_container_width=True, 
                    height=400, 
                    key="company_list_df", 
                    column_config={
                        "P/與": st.column_config.NumberColumn(format="%.2f"),
                        "70点_目安株価(円)": st.column_config.NumberColumn(format="%d"),
                        "70点_下落待ち(%)": st.column_config.NumberColumn(format="%.1f"),
                        "PBR(倍)": st.column_config.NumberColumn(format="%.2f"),
                        "PER(倍)": st.column_config.NumberColumn(format="%.2f"),
                        "配当利回り(%)": st.column_config.NumberColumn(format="%.2f")
                    },
                    on_select="rerun",
                    selection_mode="single-row"
                )
                
                if event and len(event.selection.rows) > 0:
                    selected_idx = event.selection.rows[0]
                    selected_code = df.index[selected_idx][0]
                    
                    st.divider()
                    st.markdown(f"### 👇 選択中の銘柄: [{selected_code}] の詳細データ")
                    
                    target_data = raw_data_dict[selected_code]["data"]
                    target_pyo = raw_data_dict[selected_code]["p_yo"]
                    
                    show_company_details(selected_code, target_data, target_pyo)
                
        else:
            st.warning("Firebaseにデータが登録されていません。データ収集プログラムを実行してください。")
            
    except Exception as e:
        st.error(f"データの取得中にエラーが発生しました: {e}")