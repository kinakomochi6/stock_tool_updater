import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import plotly.graph_objects as go
import pandas as pd
import requests
import zipfile
import io
from bs4 import BeautifulSoup
import datetime
import time
import re
import numpy as np
import unicodedata

# ページの設定
st.set_page_config(page_title="企業バリュー検索アプリ", page_icon="🏢", layout="wide")

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
# 1. Firebaseの接続設定（ローカル/クラウド両対応版）
# ==========================================
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        # Streamlit CloudのSecretsに設定がある場合はそちらを使う
        if "firebase" in st.secrets:
            # secretsから辞書型として読み込む
            cert_dict = dict(st.secrets["firebase"])
            cred = credentials.Certificate(cert_dict)
        else:
            # ローカル環境（あなたのPC）で動かす場合は今まで通りJSONファイルを使う
            cred = credentials.Certificate('firebase_key.json')
            
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = init_firebase()

# ==========================================
# 2. 独自ロジック群
# ==========================================
def calculate_p_yo(data):
    # ① B/S項目の倍率計算
    raw_adj_bs_asset = 0
    for key, multiplier in MULTIPLIERS.items():
        val = data.get(key, 0)
        raw_adj_bs_asset += val * multiplier
        
    # ② 有価証券の含み益に0.3をかけたものを引く（潜在的な税金負債の控除）
    sec_profit = data.get('有価証券_含み益_億', 0)
    tax_deduction = sec_profit * 0.3
    adj_bs_asset = raw_adj_bs_asset - tax_deduction
        
    # ③ 調整済み不動産額の計算
    market_val = data.get('不動産_時価_億', 0)
    book_val = data.get('不動産_簿価_億', 0)
    adj_re_val = 0
    if market_val > 0:
        adj_re_val = market_val - (book_val * 0.15) - ((market_val - book_val) * 0.3)
        
    # ④ お買い得度とP/與の計算
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
        "実質総資産": round(adj_bs_asset + adj_re_val, 2),
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

    if isinstance(p_yo, (int, float)):
        if p_yo <= 0.5:
            score += 40
            messages.append("🔥 【超絶割安】実質PBR(P/與)が0.5以下です！(解散価値の半額以下)")
        elif p_yo <= 0.8:
            score += 20
            messages.append("✅ 【割安】実質PBR(P/與)が0.8以下です")

    if 0 < pbr <= 0.5:
        score += 20
        messages.append("✅ 表面上のPBRも0.5倍以下")

    if real_estate_profit > 0 or sec_profit > 0:
        total_hidden_profit = real_estate_profit + sec_profit
        if market_cap > 0 and total_hidden_profit >= market_cap:
            score += 30
            messages.append(f"🔥 不動産＋有価証券の含み益({total_hidden_profit}億)が時価総額を上回っています！")
        elif market_cap > 0 and total_hidden_profit >= (market_cap * 0.3):
            score += 15
            messages.append("✅ 時価総額に対して30%以上の含み益(不動産・株式等)あり")

    if roe >= 8: score += 10
    return min(score, 100), messages

# ==========================================
# 3. メニュー（サイドバー）設定
# ==========================================
st.sidebar.title("メニュー")
st.sidebar.markdown("ご覧になりたい機能を選択してください。")
page = st.sidebar.radio(" ", ["🔍 個別銘柄を検索", "📋 全銘柄一覧（スクリーニング）"])
st.sidebar.divider()
st.sidebar.caption("データソース: JPX / Yahoo Finance / EDINET")

# ==========================================
# 4. ページごとの表示処理
# ==========================================

if page == "🔍 個別銘柄を検索":
    st.title("🏢 企業バリュー検索アプリ")
    
    col_search, _ = st.columns([1, 2])
    with col_search:
        search_code = st.text_input("証券コード（4桁）を入力", "3123", max_chars=4)
        search_btn = st.button("検索する", type="primary", use_container_width=True)

    if search_btn and search_code:
        with st.spinner('データベースから取得中...'):
            doc_ref = db.collection('companies').document(search_code)
            doc = doc_ref.get()
            
        if doc.exists:
            data = doc.to_dict()
            p_yo_data = calculate_p_yo(data)
            
            st.header(f"[{search_code}] {data.get('企業名', '名称不明')}")
            st.caption(f"業種: {data.get('業種', '-')} | 市場: {data.get('市場', '-')} | 最終更新: {data.get('データ最終更新日', '')}")
            
            val_score, val_msgs = calculate_value_score(data, p_yo_data)
            
            if val_score >= 70: st.success(f"### 💎 総合バリュースコア: {val_score} / 100点 (超お宝銘柄の可能性！)")
            elif val_score >= 40: st.info(f"### ⭐ 総合バリュースコア: {val_score} / 100点 (割安圏内)")
            else: st.warning(f"### 総合バリュースコア: {val_score} / 100点")
                
            if val_msgs: st.markdown("\n".join([f"- {msg}" for msg in val_msgs]))
            st.divider()

            tab1, tab2, tab3 = st.tabs(["📊 サマリー", "🥧 財務グラフ", "📋 詳細データ一覧"])

            with tab1:
                st.subheader("💡 重要指標")
                st.markdown("#### 🔥 オリジナル評価指標")
                p_yo_val = p_yo_data['P_與']
                
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("P/與 (実質PBR)", f"{p_yo_val} 倍" if p_yo_val != "-" else "-", delta="超割安！" if isinstance(p_yo_val, (int, float)) and p_yo_val < 0.8 else None, delta_color="inverse")
                mc2.metric("実質 総資産 (換金価値)", f"{p_yo_data['実質総資産']} 億円")
                mc3.metric("時価総額 (買収価格)", f"{data.get('時価総額_億', 0)} 億円")
                
                st.divider()
                st.markdown("#### 基本財務指標")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("現在の株価", f"{data.get('株価', 0)} 円")
                c2.metric("表面PBR", f"{data.get('PBR', 0)} 倍")
                
                # 不動産と有価証券の含み益を合算してアラート用に使う
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
                    "⑤ 実質総資産 (③+④)": f"{p_yo_data.get('実質総資産', 0)} 億円",
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
        else:
            st.error(f"証券コード「{search_code}」のデータはFirebaseに存在しません。")

elif page == "📋 全銘柄一覧（スクリーニング）":
    st.title("📋 全銘柄一覧 (スクリーニング)")
    st.markdown("Firebaseに保存されている全銘柄の全指標を一覧表示します。**表のヘッダーをクリックすると並び替えができます。**")

    with st.spinner("データベースから全銘柄を読み込み・計算中..."):
        try:
            docs = db.collection('companies').stream()
            
            all_data_list = []
            for doc in docs:
                data = doc.to_dict()
                code = doc.id
                
                p_yo_data = calculate_p_yo(data)
                score, _ = calculate_value_score(data, p_yo_data)
                
                p_yo_val = p_yo_data.get('P_與', None)
                if p_yo_val == "-": p_yo_val = None

                all_data_list.append({
                    "コード": code,
                    "企業名": data.get('企業名', '名称不明'),
                    "バリュースコア": score,
                    "P/與": p_yo_val,
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
                    "市場": data.get('市場', '-'),
                    "業種": data.get('業種', '-')
                })
                
            if all_data_list:
                df = pd.DataFrame(all_data_list)
                df.set_index(['コード', '企業名'], inplace=True)
                
                st.success(f"合計 **{len(df)}** 件の企業データを取得しました！")
                st.info("💡 **操作Tips:** 表の上にマウスカーソルを置き、**「Shiftキー」を押しながら「マウスホイール」を回す**と、スイスイと横にスクロールできます！")
                
                st.dataframe(
                    df, 
                    use_container_width=True, 
                    height=600,
                    column_config={
                        "P/與": st.column_config.NumberColumn(format="%.2f"),
                        "PBR(倍)": st.column_config.NumberColumn(format="%.2f"),
                        "PER(倍)": st.column_config.NumberColumn(format="%.2f"),
                        "配当利回り(%)": st.column_config.NumberColumn(format="%.2f")
                    }
                )
            else:
                st.warning("Firebaseにデータが登録されていません。データ収集プログラムを実行してください。")
                
        except Exception as e:
            st.error(f"データの取得中にエラーが発生しました: {e}")