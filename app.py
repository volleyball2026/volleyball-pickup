import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import random
import copy
from datetime import datetime, timedelta
import re
import time
import altair as alt
import plotly.graph_objects as go 
import base64  
import os
from streamlit.web.server.websocket_headers import _get_websocket_headers

# [설정] 페이지 설정은 반드시 import 바로 아래, 맨 처음에 와야 합니다!
st.set_page_config(page_title="여순광 배구 픽업", page_icon="🏐", layout="wide") 

# [UI] 모바일 최적화 CSS
st.markdown("""
    <style>
        .block-container { padding-top: 1rem !important; padding-bottom: 5rem !important; }
        header[data-testid="stHeader"] { background-color: rgba(0,0,0,0); z-index: 1; }
        div[data-testid="stTabsNav"] { position: sticky; top: 0; z-index: 999; background-color: white; padding: 10px 0; border-bottom: 1px solid #f0f0f0; }
        div[data-baseweb="tab-list"] { gap: 8px; overflow-x: auto; flex-wrap: nowrap; white-space: nowrap; scrollbar-width: none; padding-bottom: 5px; padding-left: 5px; }
        div[data-baseweb="tab-list"]::-webkit-scrollbar { display: none; }
        button[data-baseweb="tab"] { height: 40px !important; min-height: 40px !important; border-radius: 20px !important; padding: 0 20px !important; background-color: #f7f7f7 !important; border: 1px solid #eee !important; color: #666 !important; font-size: 14px !important; font-weight: 500 !important; flex: 0 0 auto; transition: all 0.2s; }
        button[data-baseweb="tab"][aria-selected="true"] { background-color: #E3F2FD !important; color: #1565C0 !important; border: 1px solid #1565C0 !important; font-weight: 800 !important; transform: scale(1.02); }
        button[data-baseweb="tab"] p { margin: 0; }
        div[data-testid="stForm"] button[kind="secondaryFormSubmit"] { background-color: #1565C0 !important; color: white !important; border: none !important; border-radius: 12px !important; padding: 0.75rem 1rem !important; font-size: 1.1rem !important; font-weight: 800 !important; box-shadow: 0 4px 6px rgba(0,0,0,0.2) !important; width: 100% !important; }
        div[data-testid="stForm"] button[kind="secondaryFormSubmit"]:active { transform: scale(0.98); }
    </style>
""", unsafe_allow_html=True)

# --- [기본 환경 설정] ---
DOC_NAME = "배구픽업관리"
SHEET_APPLICANTS = "참가자명단"
SHEET_GAME_INFO = "게임정보"
SHEET_HISTORY = "경기기록"
SHEET_BLACKLIST = "블랙리스트"
SHEET_MVP = "MVP투표"
SHEET_SUGGESTION = "건의함"
SHEET_VIDEOS = "영상관리"
SHEET_LOGS = "접속로그"
ADMIN_PASSWORD = "1992"
MAX_CAPACITY = 20

POSITIONS_ALL = ["레프트", "속공", "세터", "라이트", "앞차", "백차", "레프트백", "센터백", "라이트백"]
POSITIONS_3RD = ["레프트백", "센터백", "라이트백", "속공"]
LEVELS = ["입문", "초급", "중급", "상급", "최상급"]
POSITION_QUOTAS = {"세터": 1, "레프트": 1, "라이트": 1, "속공": 1, "앞차": 1, "백차": 1, "레프트백": 1, "센터백": 1, "라이트백": 1}
LEVEL_MAP = {"입문": 1, "초급": 2, "중급": 3, "상급": 4, "최상급": 5}

# --- [세션 상태 초기화] ---
if 'admin_logged_in' not in st.session_state: st.session_state['admin_logged_in'] = False
if 'mvp_voter_verified' not in st.session_state: st.session_state['mvp_voter_verified'] = False
if 'mvp_voter_name' not in st.session_state: st.session_state['mvp_voter_name'] = ""
if 'mvp_voter_phone' not in st.session_state: st.session_state['mvp_voter_phone'] = ""

try:
    query_params = st.query_params
    if query_params.get("auth", "") == ADMIN_PASSWORD:
        st.session_state['admin_logged_in'] = True
except: pass

# ==========================================
# [최적화] 구글 시트 연결 및 자동 복구 로직
# ==========================================
@st.cache_resource(ttl=3600)
def get_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name(r"C:\Users\82106\service_account.json", scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"🔑 인증 오류: {e}")
        return None

def get_sheet_instance(sheet_name, retries=2):
    client = get_connection()
    if not client: return None
    for attempt in range(retries):
        try:
            doc = client.open(DOC_NAME)
            return doc.worksheet(sheet_name)
        except gspread.exceptions.APIError as e:
            if "429" in str(e): 
                time.sleep(1.5)
                if attempt == retries - 1: st.toast("⚠️ 트래픽이 많습니다. 잠시 후 다시 시도해주세요.", icon="⏳")
            else:
                if attempt == retries - 1: st.error(f"API 에러: {e}")
        except gspread.exceptions.SpreadsheetNotFound:
            st.error(f"❌ '{DOC_NAME}' 시트를 찾을 수 없습니다!")
            return None
        except gspread.WorksheetNotFound:
            try:
                doc = client.open(DOC_NAME)
                return doc.add_worksheet(title=sheet_name, rows=100, cols=20)
            except: return None
        except Exception:
            st.cache_resource.clear()
            time.sleep(1)
    return None

# ==========================================
# [유틸리티 & 공평 시스템 기반 함수]
# ==========================================
def get_client_ip():
    try:
        headers = _get_websocket_headers()
        if headers:
            if "X-Forwarded-For" in headers: return headers["X-Forwarded-For"].split(",")[0]
            elif "Remote-Addr" in headers: return headers["Remote-Addr"]
    except: pass
    return "unknown"

def log_visit(action_type, user_info="익명"):
    try:
        client_ip = get_client_ip()
        now_kst = datetime.utcnow() + timedelta(hours=9)
        sheet = get_sheet_instance(SHEET_LOGS)
        if sheet:
            rows = sheet.get_all_values()
            if len(rows) > 1 and len(rows[-1]) >= 4:
                try:
                    last_dt = datetime.strptime(rows[-1][0], "%Y-%m-%d %H:%M:%S")
                    if rows[-1][3] == client_ip and (now_kst - last_dt).total_seconds() < 180: return 
                except: pass
            if not rows: sheet.append_row(["일시", "유형", "접속자(추정)", "IP주소"])
            sheet.append_row([now_kst.strftime("%Y-%m-%d %H:%M:%S"), action_type, user_info, client_ip])
    except: pass

def normalize_phone(phone):
    if not phone: return ""
    phone = re.sub(r'\D', '', str(phone))
    if len(phone) == 11: return f"{phone[:3]}-{phone[3:7]}-{phone[7:]}"
    elif len(phone) == 10: return f"{phone[:3]}-{phone[3:6]}-{phone[6:]}"
    return phone

def anonymize_name(name):
    if not isinstance(name, str): return str(name)
    # 과거 타팀 태그 흔적이 있어도 깔끔하게 무시하고 이름만 추출
    real_name = name.replace("[BLACK] ", "").replace("[VEGA] ", "").replace("[BLACK]", "").replace("[VEGA]", "").strip()
    if len(real_name) <= 1: return real_name
    elif len(real_name) == 2: return real_name[0] + "O"
    else: return real_name[0] + "O" + real_name[2:]

def simplify_level_name(level_full):
    if not isinstance(level_full, str): return str(level_full)
    return level_full.split(" ")[0]

def format_score_html(score, reason):
    if reason is None: reason = ""
    try: header = f"점수: {float(score):.2f}"
    except: header = f"점수: {score}"
    
    formatted_items = []
    for item in reason.split():
        if item.startswith('+'): formatted_items.append(f"<span style='color:#1E88E5; font-weight:bold;'>{item}</span>")
        elif item.startswith('-'): formatted_items.append(f"<span style='color:#E53935; font-weight:bold;'>{item}</span>")
        elif item.startswith('기본'): formatted_items.append(f"<span style='color:#424242; font-weight:bold;'>{item}</span>")
        else: formatted_items.append(item)
    return f"<div style='background-color: #F8F9FA; border: 1px solid #E0E0E0; border-radius: 6px; padding: 4px 8px; margin-top: 4px; color: #333333; font-size: 0.85em; line-height: 1.4;'><span style='font-weight:bold; color:#333;'>└ {header}</span> | {' '.join(formatted_items)}</div>"

# --- [데이터 관리 함수] ---
@st.cache_data(ttl=60)
def get_current_game_info():
    sheet = get_sheet_instance(SHEET_GAME_INFO)
    if sheet:
        data = sheet.get_all_values()
        if len(data) > 1:
            headers, last_row = data[0], data[-1]
            game = dict(zip(headers, last_row))
            if len(last_row) >= 10: game['공개여부'] = last_row[9]
            else: game['공개여부'] = 'X'
            return game
    return None

def save_game_info(info):
    sheet = get_sheet_instance(SHEET_GAME_INFO)
    if sheet:
        sheet.append_row([
            info['제목'], info['일시'], info['장소'], info['성별'], 
            info['참가비'], info['계좌'], info['설명'], info['연락처'], info['마감일시'], "X", "X" 
        ])
        st.cache_data.clear()

def toggle_game_visibility(is_visible):
    sheet = get_sheet_instance(SHEET_GAME_INFO)
    if sheet:
        try:
            data = sheet.get_all_values()
            if len(data) > 1:
                sheet.update_cell(len(data), 10, "O" if is_visible else "X")
                st.cache_data.clear()
                return True
        except: return False
    return False

def archive_current_game():
    src_sheet = get_sheet_instance(SHEET_APPLICANTS)
    dst_sheet = get_sheet_instance(SHEET_HISTORY)
    game_info = get_current_game_info()
    if src_sheet and dst_sheet and game_info:
        data = src_sheet.get_all_records()
        if not dst_sheet.get_all_values():
            dst_sheet.append_row(['일시', '게임제목', '이름', '연락처', '1순위', '레벨', '확정포지션'])
        if data:
            rows = []
            for p in data:
                rows.append([
                    game_info.get('일시', datetime.now().strftime("%Y-%m-%d")), game_info.get('제목', 'Untitled'), 
                    p.get('이름', ''), p.get('연락처', ''), p.get('1순위', ''), p.get('레벨', ''), p.get('확정1', '') 
                ])
            dst_sheet.append_rows(rows)
        st.cache_data.clear()

@st.cache_data(ttl=15)
def load_applicants():
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        try: return sheet.get_all_records()
        except: pass
    return []

def add_applicant(name, phone, level, pos1, pos2, pos3, note, excluded_str):
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        sheet.append_row([
            name, normalize_phone(phone), level, pos1, pos2, pos3, 
            "", "", "", "", "", "", "", "", 
            anonymize_name(name), "X", note, excluded_str, "O"
        ])
        st.cache_data.clear()

def cancel_applicant(name, phone):
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        clean_phone = normalize_phone(phone)
        try:
            cell_list = sheet.findall(name)
            for cell in cell_list:
                if normalize_phone(sheet.cell(cell.row, 2).value) == clean_phone:
                    sheet.delete_rows(cell.row)
                    st.cache_data.clear()
                    return True, "취소되었습니다."
            return False, "정보가 일치하지 않습니다."
        except: return False, "오류 발생"

def update_lineup(df):
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        sheet.clear()
        headers = ["이름", "연락처", "레벨", "1순위", "2순위", "3순위", "팀1", "팀2", "팀3", "팀4", "확정1", "확정2", "확정3", "확정4", "이름(가림)", "입금", "비고", "제외", "참가여부"]
        sheet.append_row(headers)
        if '참가여부' not in df.columns: df['참가여부'] = 'O'
        for col in headers:
            if col not in df.columns: df[col] = ""
        sheet.append_rows(df[headers].values.tolist())
        st.cache_data.clear()

def clear_applicants():
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        sheet.clear()
        sheet.append_row(["이름", "연락처", "레벨", "1순위", "2순위", "3순위", "팀1", "팀2", "팀3", "팀4", "확정1", "확정2", "확정3", "확정4", "이름(가림)", "입금", "비고", "제외", "참가여부"])
        st.cache_data.clear()

def check_blacklist(name, phone):
    sheet = get_sheet_instance(SHEET_BLACKLIST)
    if sheet:
        clean_phone = normalize_phone(phone)
        for row in sheet.get_all_records():
            if row['이름'] == name and normalize_phone(row['연락처']) == clean_phone:
                return True, row['사유']
    return False, ""

def add_to_blacklist(name, phone, reason):
    sheet = get_sheet_instance(SHEET_BLACKLIST)
    if sheet: sheet.append_row([name, normalize_phone(phone), reason, datetime.now().strftime("%Y-%m-%d")])

@st.cache_data(ttl=60)
def get_my_history(name, phone):
    sheet = get_sheet_instance(SHEET_HISTORY)
    history = []
    if sheet:
        try:
            clean_phone = normalize_phone(phone)
            for row in sheet.get_all_records():
                if str(row.get('게임제목')) == 'CLOSED' or str(row.get('일시')) == '-': continue
                if row.get('이름') == name and normalize_phone(row.get('연락처')) == clean_phone:
                    history.append(row)
        except: pass
    return history

@st.cache_data(ttl=60)
def load_all_history():
    sheet = get_sheet_instance(SHEET_HISTORY)
    if not sheet: return []
    try: return sheet.get_all_records()
    except: return []

# --- 영상/건의/MVP 등 부가 기능 ---
def save_video_link(url, title):
    sheet = get_sheet_instance(SHEET_VIDEOS)
    if sheet:
        if not sheet.get_all_values(): sheet.append_row(["날짜", "제목", "URL"])
        sheet.append_row([datetime.now().strftime("%Y-%m-%d"), title, url])
        st.cache_data.clear()

@st.cache_data(ttl=60)
def get_latest_video():
    sheet = get_sheet_instance(SHEET_VIDEOS)
    if sheet:
        try:
            rows = sheet.get_all_values()
            if len(rows) > 1 and len(rows[-1]) >= 3:
                return {"date": rows[-1][0], "title": rows[-1][1], "url": rows[-1][2]}
        except: pass
    return None

def save_mvp_vote(voter, phone, mvp_candidate):
    sheet = get_sheet_instance(SHEET_MVP)
    if sheet:
        clean_phone = normalize_phone(phone)
        today = datetime.now().strftime("%Y-%m-%d")
        for row in sheet.get_all_records():
            if row['투표자이름'] == voter and normalize_phone(row['투표자연락처']) == clean_phone and row['일시'] == today:
                return False, "이미 투표하셨습니다."
        sheet.append_row([today, voter, clean_phone, mvp_candidate])
        st.cache_data.clear()
        return True, "투표 완료!"
    return False, "오류"

@st.cache_data(ttl=15)
def get_mvp_ranking_today():
    sheet = get_sheet_instance(SHEET_MVP)
    if sheet:
        data = sheet.get_all_records()
        today = datetime.now().strftime("%Y-%m-%d")
        votes = [row['MVP후보'] for row in data if row.get('일시') == today]
        if votes:
            df = pd.DataFrame(votes, columns=['이름'])
            ranking = df['이름'].value_counts().reset_index()
            ranking.columns = ['이름', '득표수']
            return ranking
    return pd.DataFrame()

@st.cache_data(ttl=60)
def get_mvp_hall_of_fame():
    sheet = get_sheet_instance(SHEET_MVP)
    if sheet:
        data = sheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            if '일시' in df.columns and 'MVP후보' in df.columns:
                daily_counts = df.groupby(['일시', 'MVP후보']).size().reset_index(name='득표수')
                idx = daily_counts.groupby(['일시'])['득표수'].transform(max) == daily_counts['득표수']
                return daily_counts[idx].sort_values('일시', ascending=False)
    return []

def save_suggestion(message):
    sheet = get_sheet_instance(SHEET_SUGGESTION)
    if sheet:
        sheet.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message, "대기중", ""])
        st.cache_data.clear()
        return True
    return False

def update_suggestions(df):
    sheet = get_sheet_instance(SHEET_SUGGESTION)
    if sheet:
        sheet.clear()
        sheet.append_row(["일시", "내용", "상태", "답변"])
        sheet.append_rows(df.values.tolist())
        st.cache_data.clear()

@st.cache_data(ttl=60)
def load_suggestions():
    sheet = get_sheet_instance(SHEET_SUGGESTION)
    if sheet: return sheet.get_all_records()
    return []

@st.cache_data(ttl=60)
def get_my_mvp_stats(name, phone):
    sheet = get_sheet_instance(SHEET_MVP)
    received, voted = 0, 0
    if sheet:
        clean_phone = normalize_phone(phone)
        for row in sheet.get_all_records():
            if row.get('MVP후보') == name: received += 1
            if row.get('투표자이름') == name and normalize_phone(row.get('투표자연락처')) == clean_phone: voted += 1
    return received, voted

def draw_radar_chart(stats):
    categories = ['🔥참여율', '✨매너', '❤️헌신', '🌈다양성', '🤝사교성']
    values = [stats['participation'], stats['manner'], stats['dedication'], stats['diversity'], stats['social']]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=values, theta=categories, fill='toself', name='Stats', line=dict(color='#FF5722'), fillcolor='rgba(255, 87, 34, 0.4)'))
    fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100], showticklabels=False)), showlegend=False, margin=dict(l=40, r=40, t=30, b=30), height=300, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return fig

def generate_kakao_text(df):
    text = "🏐 [이번 주 배구 픽업 라인업] 🏐\n\n"
    for i, (col_team, col_pos) in enumerate([("팀1", "확정1"), ("팀2", "확정2"), ("팀3", "확정3")], 1):
        if col_pos not in df.columns: continue
        text += f"==== {i*2-1}·{i*2}세트 ====\n"
        playing = df[df[col_pos] != '']
        if playing.empty: text += "(미정)\n\n"; continue
        text += "🔴 A팀\n"
        for _, r in playing[(playing[col_team]=="A팀") & (playing[col_pos]!="대기")].iterrows(): text += f"- {r[col_pos]}: {r['이름']}\n"
        text += "\n🔵 B팀\n"
        for _, r in playing[(playing[col_team]=="B팀") & (playing[col_pos]!="대기")].iterrows(): text += f"- {r[col_pos]}: {r['이름']}\n"
        text += "\n🛌 대기\n"
        bench = playing[playing[col_pos] == "대기"]
        if bench.empty: text += "-\n"
        else:
            for _, r in bench.iterrows(): text += f"- {r['이름']}\n"
        text += "\n"
    return text

# --- [UI] 시각화 생성 함수 (배지 제거, 공평 시스템) ---
def render_applicant_list_html(df):
    if df.empty: return "<div style='text-align:center; padding:20px; color:#999;'>아직 신청자가 없습니다.</div>"
    
    POS_ABBR = {"레프트": "레", "라이트": "라", "세터": "세", "속공": "속", "앞차": "앞", "백차": "백", "레프트백": "레백", "라이트백": "라백", "센터백": "센백", "선택 안함": "-", "": "-", "nan": "-"}
    html_code = "<div style='display: grid; grid-template-columns: 1fr 1fr; gap: 10px;'>"
    
    for _, row in df.iterrows():
        name = row['이름']
        level = row.get('레벨', '입문')
        p1, p2, p3 = str(row.get('1순위', '-')).strip(), str(row.get('2순위', '-')).strip(), str(row.get('3순위', '-')).strip()
        
        abbr1 = POS_ABBR.get(p1, p1[:1])
        chain_str = abbr1
        if p2 and p2 not in ["선택 안함", "-", "nan", ""]: chain_str += f"-{POS_ABBR.get(p2, p2[:1])}"
        if p3 and p3 not in ["선택 안함", "-", "nan", ""]: chain_str += f"-{POS_ABBR.get(p3, p3[:1])}"

        note = str(row.get('비고', ''))
        status_bool = str(row.get('입금', '')).upper() == 'O'
        display_name = anonymize_name(name)
        
        if status_bool: status_icon, bg_color, border_color, opacity = "✅", "#FFFFFF", "#E0E0E0", "1.0"
        else: status_icon, bg_color, border_color, opacity = "⏳", "#F9F9F9", "#EEEEEE", "0.7"
            
        top_badges = ""
        if "예비" in note: top_badges += "<span style='background:#FFF3E0; color:#E65100; font-size:0.6rem; padding:2px 5px; border-radius:10px;'>대기</span>"
        elif "지각" in note: top_badges += "<span style='background:#FFEBEE; color:#D32F2F; font-size:0.6rem; padding:2px 5px; border-radius:10px;'>지각</span>"

        card = (
            f"<div style='background-color: {bg_color}; border: 1px solid {border_color}; border-radius: 15px; padding: 12px 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); text-align: center; opacity: {opacity}; position: relative;'>"
            f"  <div style='position: absolute; top: 8px; right: 8px; font-size: 0.8em;'>{status_icon}</div>"
            f"  <div style='display: flex; justify-content: center; margin-bottom: 6px;'><div style='width: 35px; height: 35px; border-radius: 50%; background-color: #f0f2f6; color: #444; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: { '0.85em' if len(abbr1) > 1 else '1.0em' }; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>{abbr1}</div></div>"
            f"  <div style='margin-bottom: 4px; min-height: 15px;'>{top_badges}</div>"
            f"  <div style='font-size: 1.1em; font-weight: 800; color: #222; margin-bottom: 2px; letter-spacing: -0.5px;'>{display_name}</div>"
            f"  <div style='font-size: 0.75em; color: #666; letter-spacing: -0.5px; font-weight: 600;'>{level} · <span style='color:#1565C0;'>{chain_str}</span></div>"
            f"</div>"
        )
        html_code += card
    html_code += "</div>"
    return html_code

def render_tactical_board(team_df, team_type, col_pos, score_db=None, r_num=None):
    if team_type == "A팀": bg_color, border_color, header_text = "#FFEBEE", "#D32F2F", "🔴 A팀"
    else: bg_color, border_color, header_text = "#E3F2FD", "#1976D2", "🔵 B팀"

    player_map = {}
    if not team_df.empty and col_pos in team_df.columns:
        players = team_df[team_df[col_pos] != "대기"]
        for _, row in players.iterrows():
            pos = str(row.get(col_pos, '')).strip()
            real_name = row['이름']
            name = anonymize_name(real_name)
            
            score, reason = 0, ""
            if score_db and r_num:
                if real_name in score_db.get(r_num, {}):
                    p_data = score_db[r_num][real_name]
                    score = p_data['score']
                    reason = p_data.get('reason', '')
            else:
                score = row.get('priority_score', 0)
                reason = row.get('score_reason', '')
            
            w1, w2, w3 = str(row.get('1순위', '')).strip(), str(row.get('2순위', '')).strip(), str(row.get('3순위', '')).strip()
            rank_badge = "1st" if pos == w1 else "2nd" if pos == w2 else "3rd" if pos == w3 else "random"
            player_map[pos] = {"name": name, "score": score, "reason": reason, "rank": rank_badge, "real_name": real_name}

    def make_player_html(pos_name):
        p_data = player_map.get(pos_name)
        if p_data:
            display_name = p_data['name']
            p_score_txt = f"{p_data['score']:.2f}"
            p_rank = p_data['rank']
            
            if p_rank == "1st": rank_html = "<span style='color:#1565C0; background-color:#E3F2FD; padding:0px 3px; border-radius:3px; font-size:0.7em; font-weight:normal; margin-left:3px;'>1순위</span>"
            elif p_rank == "2nd": rank_html = "<span style='color:#2E7D32; background-color:#E8F5E9; padding:0px 3px; border-radius:3px; font-size:0.7em; font-weight:normal; margin-left:3px;'>2순위</span>"
            elif p_rank == "3rd": rank_html = "<span style='color:#EF6C00; background-color:#FFF3E0; padding:0px 3px; border-radius:3px; font-size:0.7em; font-weight:normal; margin-left:3px;'>3순위</span>"
            else: rank_html = "<span style='color:#C62828; background-color:#FFEBEE; padding:0px 3px; border-radius:3px; font-size:0.7em; font-weight:normal; margin-left:3px;'>무</span>"

            formatted_reason = "".join([f"<span style='color: {'#1976D2' if i.startswith('+') else '#D32F2F' if i.startswith('-') else '#9E9E9E'}; margin-right:2px;'>{i}</span>" for i in p_data['reason'].split()])
            
            return (
                f"<div style='background: white; border: 1px solid {border_color}; border-radius: 6px; padding: 4px 1px; margin: 1px; width: 24%; box-shadow: 1px 1px 2px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 60px;'>"
                f"<div style='font-size: 0.55em; font-weight: bold; color: #888; margin-bottom: 1px; white-space: nowrap;'>{pos_name}{rank_html}</div>"
                f"<div style='font-size: 0.8em; font-weight: 800; margin-bottom: 1px; line-height: 1.1; text-align: center; word-break: break-word; overflow-wrap: break-word;'>{display_name}</div>"
                f"<div style='font-size: 0.7em; font-weight:bold; color: #333; border-bottom: 1px solid #eee; margin-bottom: 2px;'>{p_score_txt}</div>"
                f"<div style='font-size: 0.5em; line-height: 1; text-align: center; word-break: break-all;'>{formatted_reason}</div>"
                f"</div>"
            )
        else:
            return f"<div style='border: 1px dashed #ddd; border-radius: 6px; padding: 4px 1px; margin: 1px; width: 24%; opacity: 0.6; display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 60px;'><div style='font-size: 0.55em; color: #aaa;'>{pos_name}</div><div style='font-size: 0.65em; color: #ccc;'>(공석)</div></div>"

    board_html = (
        f"<div style='background-color: {bg_color}; border: 1px solid {border_color}; border-radius: 10px; padding: 6px 2px; margin-bottom: 10px;'><div style='text-align: center; font-weight: bold; color: {border_color}; font-size: 0.85em; margin-bottom: 4px;'>{header_text}</div>"
        f"<div style='display: flex; justify-content: space-around; margin-bottom: 4px;'>{make_player_html('레프트')}{make_player_html('속공')}{make_player_html('세터')}{make_player_html('라이트')}</div>"
        f"<div style='display: flex; justify-content: center; gap: 15px; margin-bottom: 4px;'>{make_player_html('앞차')}{make_player_html('백차')}</div>"
        f"<div style='display: flex; justify-content: space-around;'>{make_player_html('레프트백')}{make_player_html('센터백')}{make_player_html('라이트백')}</div></div>"
    )
    return board_html

# --- [공평 알고리즘] ---
def get_priority_score(player, global_history, global_hardship):
    name = player['이름']
    score = 50.0 
    reasons = ["기본(50)"]
    
    success_count = global_history.get(name, 0)
    if success_count > 0:
        penalty = success_count * 10.0
        score -= penalty
        reasons.append(f"-배정{success_count}회({int(penalty)})")
        
    hardship_score = global_hardship.get(name, 0)
    if hardship_score > 0:
        score += hardship_score
        reasons.append(f"+마일리지({int(hardship_score)})")
        
    game_info = get_current_game_info()
    game_date = str(game_info.get('일시', 'default')) if game_info else 'default'
    seed_key = f"{name}_{game_date}"
    score += round(random.Random(seed_key).random(), 2)
    
    return score, " ".join(reasons)

def assign_positions_in_team(team_members):
    team_members.sort(key=lambda x: x['priority_score'], reverse=True)
    for p in team_members: 
        p['assigned_pos'] = None
        p['match_type'] = 'random'
    
    total_cnt = len(team_members)
    court_capacity = 9
    if total_cnt > court_capacity:
        safe_zone = team_members[:court_capacity]
        drop_zone = team_members[court_capacity:]
        rare_positions = ["세터", "속공", "라이트", "레프트"]
        
        for p_drop in drop_zone:
            wish = str(p_drop.get('1순위', '')).strip()
            if wish in rare_positions:
                has_pos_in_safe = any(str(p.get('1순위', '')).strip() == wish for p in safe_zone)
                if not has_pos_in_safe:
                    swap_target_idx = -1
                    for i in range(len(safe_zone)-1, -1, -1):
                        p_safe = safe_zone[i]
                        if str(p_safe.get('1순위', '')).strip() not in rare_positions:
                            swap_target_idx = i
                            break
                    if swap_target_idx != -1:
                        idx_safe, idx_drop = team_members.index(safe_zone[swap_target_idx]), team_members.index(p_drop)
                        team_members[idx_safe], team_members[idx_drop] = team_members[idx_drop], team_members[idx_safe]
                        safe_zone, drop_zone = team_members[:court_capacity], team_members[court_capacity:]

    starters = team_members[:9] if total_cnt >= 9 else team_members
    quotas = POSITION_QUOTAS.copy()
    count_fast = [str(p.get('1순위', '')).strip() for p in starters].count('속공')
    team_size_court = len(starters)
    
    if team_size_court == 8:
        if count_fast > 0: quotas['센터백'] = 0 
        else: quotas['속공'] = 0 
    elif team_size_court == 7: quotas['속공'] = 0; quotas['센터백'] = 0
    elif team_size_court == 6: quotas['속공'] = 0; quotas['센터백'] = 0; quotas['백차'] = 0

    for p in team_members:
        if not p['assigned_pos']:
            for step in [1, 2, 3]:
                wish = str(p.get(f'{step}순위', '')).strip()
                if wish and wish != "선택 안함" and quotas.get(wish, 0) > 0:
                    if wish not in p.get('excluded', []):
                        p['assigned_pos'] = wish
                        quotas[wish] -= 1
                        if step == 1: p['match_type'] = '1st'
                        elif step == 2: p['match_type'] = '2nd'
                        elif step == 3: p['match_type'] = '3rd'
                        break

    for p in team_members:
        if not p['assigned_pos']:
            excluded_list = p.get('excluded', [])
            for pos, q in quotas.items():
                if q > 0 and pos not in excluded_list:
                    p['assigned_pos'] = pos
                    quotas[pos] -= 1
                    p['match_type'] = 'random'
                    break
    
    for p in team_members:
        if not p['assigned_pos']:
            p['assigned_pos'] = "대기"
            p['match_type'] = 'wait'
                
    return team_members
    
def generate_priority_schedule(df):
    if '참가여부' not in df.columns: df['참가여부'] = 'O'
    raw_data = df.to_dict('records')
    valid_candidates = [p for p in raw_data if str(p.get('참가여부', 'O')).upper().strip() != 'X']
    
    base_players = []
    for idx, p in enumerate(valid_candidates):
        if idx < MAX_CAPACITY: base_players.append(p)
            
    for p in base_players:
        ex_str = str(p.get('제외', ''))
        p['excluded'] = [x.strip() for x in ex_str.split(',') if x.strip()] if ex_str else []

    global_history = {p['이름']: 0 for p in base_players}
    global_hardship = {p['이름']: 0 for p in base_players}
    final_rounds = {}

    for round_num in range(1, 5):
        target_set = f"{round_num*2-1}·{round_num*2}"
        valid_markers = ["1·2", "3·4", "5·6"]
        
        current_pool = []
        for p in base_players:
            note = str(p.get('비고', ''))
            has_marker = any(m in note for m in valid_markers)
            if has_marker:
                if round_num == 4: 
                    if "5·6" in note: current_pool.append(p.copy())
                else:
                    if target_set in note: current_pool.append(p.copy())
            else:
                current_pool.append(p.copy())

        for p in current_pool:
            sc, re_val = get_priority_score(p, global_history, global_hardship)
            p['priority_score'] = sc; p['score_reason'] = re_val
            
        current_pool.sort(key=lambda x: x['priority_score'], reverse=True)
        
        # 완전 공평한 스네이크 드래프트 분배 (1-A, 2-B, 3-B, 4-A)
        team_a, team_b = [], []
        for i, p in enumerate(current_pool):
            if (i % 4 == 0) or (i % 4 == 3): team_a.append(p)
            else: team_b.append(p)

        team_a.sort(key=lambda x: x['priority_score'], reverse=True)
        team_b.sort(key=lambda x: x['priority_score'], reverse=True)

        final_a = assign_positions_in_team(team_a)
        final_b = assign_positions_in_team(team_b)
        
        for p in final_a + final_b:
            nm = p['이름']; mt = p.get('match_type')
            if mt == '1st': global_history[nm] = global_history.get(nm, 0) + 1
            
            points = 0
            if mt == 'wait': points = 10
            elif mt == '3rd': points = 5
            elif mt == '2nd': points = 3
            elif mt == 'random':
                w1, w2, w3 = str(p.get('1순위', '')).strip(), str(p.get('2순위', '')).strip(), str(p.get('3순위', '')).strip()
                if w1 and w2 and w3 and w1!="선택 안함" and w2!="선택 안함" and w3!="선택 안함": points = 5 
                else: points = 3 
            
            if points > 0: global_hardship[nm] = global_hardship.get(nm, 0) + points
            
        final_rounds[round_num] = (final_a, final_b)
        
    return final_rounds

log_visit("메인접속", st.session_state.get('my_name', '익명'))

# --- [사이드바] ---
with st.sidebar:
    st.header("📢 Update Log")
    st.info("정식 출범! 100% 공평 배정 시스템 가동 시작")
    st.divider()
    st.markdown("### 📞 문의하기")
    st.markdown("💬 [**오픈채팅방 입장 (클릭)**](https://open.kakao.com/o/gf1s6t9h)")
    st.caption("🗣️ **소리함**: 우측 상단 '소리함' 탭을 이용해주세요.")
    if get_sheet_instance(SHEET_APPLICANTS): st.success("✅ 서버 연결됨")
    else: st.error("❌ 서버 연결 실패")

# --- [메인 헤더] ---
img_file = "mikasa.png" 
if os.path.exists(img_file):
    with open(img_file, "rb") as f: img_b64 = base64.b64encode(f.read()).decode()
    icon_html = f'<img src="data:image/jpeg;base64,{img_b64}" style="width: 65px; height: 65px; border-radius: 50%; box-shadow: 0 4px 6px rgba(0,0,0,0.15); object-fit: cover;">'
else: icon_html = "<div style='font-size: 3.5rem; line-height: 1;'>🏐</div>"

st.markdown(f"""
<div style='display: flex; align-items: center; gap: 15px; margin-bottom: 25px; padding-top: 10px;'>
    <div style='display:flex; align-items:center;'>{icon_html}</div>
    <div style='display: flex; flex-direction: column;'>
        <div style='font-size: 1.1rem; font-weight: bold; color: #777; letter-spacing: -0.5px; margin-bottom: -4px;'>여순광 배구 픽업</div>
        <div style='font-size: 1.9rem; font-weight: 900; color: #222; line-height: 1.1;'>게임 매니저</div>
    </div>
</div>
""", unsafe_allow_html=True)

current_game = get_current_game_info()

tab0, tab1, tab2, tab3, tab4, tab8, tab5, tab6, tab7 = st.tabs([
    "🔰 운영 안내", "📢 참가 신청", "📋 라인업 공개", "📊 My Page", "🏆 MVP", 
    "📺 경기 영상", "🗣️ 소리함", "⚡ 라인업 생성(관리자)", "⚙️ 관리자"
])

# --- 탭 0: 운영 안내 ---
with tab0:
    st.info("📢 **[안내] 여순광 배구 픽업게임 운영 안내** (필독)")
    st.markdown("""
    **여순광 픽업게임에 오신 것을 환영합니다!**
    배구를 사랑하는 마음으로 함께 즐겨주시면 감사하겠습니다.
    
    ### 📅 운동 정보
    - **시간**: 매주 월요일 (공휴일 제외) **18:00 ~ 21:00**
        - 18:00 ~ 18:30: 몸풀기
        - 18:30 ~ 19:00: 공격 및 서브 연습
        - 19:00 ~ 21:00: 경기 진행
    - **장소**: 순천조례초등학교 체육관
    - **참가비**: **미정** (추후 공지)
    
    ### 📝 진행 방법
    1. **참가 신청**: 이 웹앱의 **[📢 참가 신청]** 탭에서 신청해주세요.
        - 📅 **신청 마감**: 운동 전날 마감
        - **시간 선택**: 늦참/조기귀가 시 **참가 가능한 세트**를 꼭 체크해주세요.
        - **정원제 시행**: 선착순 **20명**까지만 경기에 참여 가능합니다.
        - **예비 등록**: 21번째 신청자부터는 **'예비 대기자'**로 등록되며, 결원 발생 시 순서대로 연락드립니다.
    2. **경기 진행**: 12명 이상 모이면 경기를 진행합니다.
    3. **성별**: **남성 경기**이며, 남성 18명 미만 시 여성은 **수비 선수로만** 참가 가능합니다.
    4. **팀 배정**: 실력 균형을 맞춘 **100% 공평한 자동 라인업 시스템**을 사용합니다.
    
    ---
    **💬 문의사항은 오픈채팅방을 이용해주세요.**
    [👉 여순광 배구 픽업 오픈채팅방 입장하기](https://open.kakao.com/o/gf1s6t9h)
    """)

# --- 탭 1: 참가 신청 ---
with tab1:
    if not current_game or current_game.get('제목') == 'CLOSED':
        st.info("💤 **현재 모집 중인 게임이 없습니다.**")
        st.markdown("### 🔜 다음 게임을 준비 중입니다!\n관리자가 새로운 게임을 개설할 때까지 잠시만 기다려주세요.\n보통 **매주 일요일**에 새로운 모집이 시작됩니다.")
        st.markdown("<div style='text-align: center; font-size: 60px; margin-top: 30px;'>🏐</div>", unsafe_allow_html=True)
    else:
        if 'reg_success' not in st.session_state: st.session_state['reg_success'] = False
        if 'reg_name' not in st.session_state: st.session_state['reg_name'] = ""
        if 'reg_type' not in st.session_state: st.session_state['reg_type'] = "normal" 

        deadline_str = str(current_game.get('마감일시', '2099-12-31 23:59'))
        try: deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
        except: deadline_dt = datetime(2099, 12, 31, 23, 59)
        now = datetime.utcnow() + timedelta(hours=9)
        is_expired = now > deadline_dt

        applicants = load_applicants()
        current_count = len(applicants)
        is_full = current_count >= MAX_CAPACITY

        st.subheader(f"[{current_game['성별']}] {current_game['제목']}")
        
        c1, c2 = st.columns(2)
        with c1: st.write(f"**📅 일시:** {current_game['일시']}"); st.write(f"**📍 장소:** {current_game['장소']}")
        with c2: 
            st.write(f"**💰 참가비:** {current_game['참가비']}")
            if is_expired: st.error(f"**⏰ 마감:** {deadline_str} (종료)")
            elif is_full: st.warning(f"**🚫 정원 도달:** {current_count}/{MAX_CAPACITY}명")
            else: st.info(f"**⏰ 마감:** {deadline_str} 까지")

        st.markdown(f"**👥 모집 현황 ({current_count} / {MAX_CAPACITY}명)**")
        st.progress(min(current_count / MAX_CAPACITY, 1.0))
        
        if is_full: st.warning(f"📢 **정원 초과!** 지금 신청 시 **'예비 대기자'**로 접수됩니다.")

        st.divider()

        if st.session_state['reg_success']:
            msg_name = st.session_state['reg_name']
            r_type = st.session_state.get('reg_type', 'normal')
            if r_type == 'waiting':
                st.warning(f"✅ {msg_name}님, **예비 대기자**로 등록되었습니다.\n결원이 생기면 연락드리겠습니다.")
            elif st.session_state.get('reg_is_late'):
                st.success(f"✅ {msg_name}님, **시간 외 대기** 명단에 등록되었습니다!\n운영진 승인 후 확정됩니다.")
            else:
                st.success(f"✅ {msg_name}님 신청 완료! 입금을 진행해주세요.")
            if st.button("확인 (닫기)"):
                st.session_state['reg_success'] = False
                st.rerun()
            st.divider()
        
        st.write("### 👇 참가 신청서")
        with st.form("apply_form"):
            c1, c2 = st.columns(2)
            with c1: name = st.text_input("이름")
            with c2: phone = st.text_input("연락처", placeholder="01012345678")
            
            with st.expander("ℹ️ 레벨 기준 보기", expanded=False):
                st.markdown("- **입문**: 기본기 부족\n- **초급**: 경험 적음\n- **중급**: 전국대회 가능\n- **상급**: 전국대회 상위\n- **최상급**: 선출 준함")
            
            st.markdown("---")
            st.write("**⏱️ 참가 가능 시간(세트) 선택**")
            set_options_data = [("1·2세트", "(18:30 ~ 19:10)"), ("3·4세트", "(19:10 ~ 19:50)"), ("5·6세트", "(19:50 ~ 20:30)"), ("7·8세트", "(잔여 시간)")]
            selected_sets = []
            with st.container(border=True):
                t_col1, t_col2 = st.columns(2)
                for i, (s_name, s_time) in enumerate(set_options_data):
                    col = t_col1 if i % 2 == 0 else t_col2
                    with col:
                        if st.checkbox(f"{s_name} {s_time}", value=True, key=f"time_{i}"):
                            selected_sets.append(f"{s_name} {s_time}")
            
            st.markdown("---")
            st.write("**🛡️ 포지션 희망 (점수 혜택)**")
            st.info("💡 **배정 꿀팁**: 1순위 경쟁에서 밀리면 **원하지 않는 포지션**으로 임의 배정될 수 있습니다.\n**2순위**와 **3순위(수비/속공)**까지 꽉 채워주셔야 **희망 포지션 배정 확률**이 높아지고, **알고리즘 가산점(+점수)**도 챙길 수 있습니다!")
            
            lc1, lc2 = st.columns(2)
            with lc1: level = st.selectbox("참가자 레벨", LEVELS)
            p1, p2, p3 = st.columns(3)
            with p1: pos1 = st.selectbox("1순위 (필수)", POSITIONS_ALL)
            with p2: pos2 = st.selectbox("2순위 (차선책)", ["선택 안함"] + POSITIONS_ALL)
            with p3: pos3 = st.selectbox("3순위 (가산점+)", ["선택 안함"] + POSITIONS_3RD)
            
            st.caption("※ 부상 등으로 **'절대 불가능한'** 포지션이 있다면 아래에서 제외하세요.")
            excluded_pos = st.multiselect("제외할 포지션 (선택)", POSITIONS_ALL, max_selections=2)
            
            if is_full: submit_label = "신청하기 (대기자 등록)"
            elif is_expired: submit_label = "시간 외 추가 등록하기"
            else: submit_label = "신청하기"
            
            if st.form_submit_button(submit_label, type="primary"):
                if name and phone:
                    if not selected_sets: st.error("❌ 최소 1개 이상의 세트를 선택해야 합니다.")
                    elif pos1 in excluded_pos: st.error("❌ 1순위 포지션은 제외할 수 없습니다.")
                    else:
                        is_black_list, reason = check_blacklist(name, phone)
                        if is_black_list: st.error(f"🚨 신청 불가: {reason}")
                        else:
                            reg_type = "waiting" if is_full else "normal"
                            note_prefix = f"[예비{current_count+1}] " if is_full else "[지각] " if is_expired else ""
                            sets_str = ", ".join([s.split("세트")[0] for s in selected_sets])
                            excluded_str = ", ".join(excluded_pos)
                            final_note = note_prefix + sets_str
                            
                            try:
                                add_applicant(name, phone, level, pos1, "" if pos2=="선택 안함" else pos2, "" if pos3=="선택 안함" else pos3, final_note, excluded_str)
                                st.session_state.update({'reg_success': True, 'reg_name': name, 'reg_is_late': is_expired, 'reg_type': reg_type})
                                st.toast("등록되었습니다!", icon="📝")
                                st.rerun()
                            except Exception as e: st.error(f"❌ 저장 중 오류: {str(e)}")
                else: st.error("필수 입력 누락"); st.toast("⚠️ 이름과 연락처를 입력해주세요!", icon="🚨")
        
        with st.expander("🗑️ 신청 취소"):
            with st.form("cancel"):
                cc1, cc2 = st.columns(2)
                with cc1: c_name = st.text_input("이름")
                with cc2: c_phone = st.text_input("연락처")
                if st.form_submit_button("취소하기"):
                    if is_expired:
                        masked_name, masked_phone = anonymize_name(c_name), c_phone[-4:] if len(c_phone) >= 4 else "****"
                        save_suggestion(f"🚨 [마감후취소] {masked_name} (뒷번호 {masked_phone}) 취소 요청")
                    suc, msg = cancel_applicant(c_name, c_phone)
                    if suc: 
                        st.success(msg); st.toast("🗑️ 취소되었습니다."); time.sleep(1.5); st.rerun() 
                    else: st.error(msg)

        st.divider()
        st.subheader("📊 실시간 참가 신청 현황")
        if applicants:
            df_public = pd.DataFrame(applicants)
            st.markdown("##### 🚦 포지션 경쟁률 (정원 내)")
            df_in_cap = df_public.iloc[:MAX_CAPACITY]
            
            if '1순위' in df_in_cap.columns:
                c1, c2, c3 = df_in_cap['1순위'].value_counts(), df_in_cap['2순위'].value_counts(), df_in_cap['3순위'].value_counts()
                st.markdown("""<style>.pos-container {display: grid; grid-template-columns: repeat(auto-fit, minmax(85px, 1fr)); gap: 8px; margin-bottom: 20px;}.pos-card {background-color: white; border: 1px solid #e0e0e0; border-radius: 10px; padding: 10px 4px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.08);}.pos-title {font-size: 0.9em; color: #444; margin-bottom: 6px; font-weight: bold; border-bottom: 1px solid #f0f0f0; padding-bottom: 6px;}.pos-main-count {font-size: 1.6em; font-weight: 900; color: #1565C0; margin-bottom: 8px; line-height: 1;}.pos-sub-info {font-size: 0.85em; color: #555; display: flex; justify-content: space-around; align-items: center; background: #F5F7FA; border-radius: 6px; padding: 6px 2px;}.sub-item {display: flex; flex-direction: column; align-items: center; width: 45%;}.sub-label {color: #888; font-size: 0.75em; margin-bottom: 2px;}.sub-val {font-size: 1.1em; font-weight: 800; color: #333;}.status-badge {font-size: 0.7em; padding: 2px 5px; border-radius: 4px; margin-left: 4px; vertical-align: middle;}.s-safe {background:#E8F5E9; color:#2E7D32;}.s-warn {background:#FFF3E0; color:#E65100;}</style>""", unsafe_allow_html=True)
                html_code = '<div class="pos-container">'
                for pos in POSITIONS_ALL:
                    cnt1, cnt2, cnt3 = c1.get(pos, 0), c2.get(pos, 0), c3.get(pos, 0)
                    status = "<span class='status-badge s-warn'>혼잡</span>" if cnt1 >= 3 else "<span class='status-badge s-safe'>빈집</span>" if cnt1 == 0 else "<span class='status-badge s-safe'>여유</span>"
                    val3_display = f"{cnt3}" if pos in POSITIONS_3RD else "-"
                    html_code += f"<div class='pos-card'><div class='pos-title'>{pos} {status}</div><div class='pos-main-count'>{cnt1}<span style='font-size:0.5em; font-weight:normal; color:#999; margin-left:2px;'>명</span></div><div class='pos-sub-info'><div class='sub-item'><span class='sub-label'>2순위</span><span class='sub-val'>{cnt2}</span></div><div style='border-right:1px solid #ddd; height:20px;'></div><div class='sub-item'><span class='sub-label'>3순위</span><span class='sub-val'>{val3_display}</span></div></div></div>"
                html_code += "</div>"
                st.markdown(html_code, unsafe_allow_html=True)
                
            st.divider()
            col_list, col_stats = st.columns([2.2, 1])
            with col_list:
                st.markdown(f"##### 📋 신청자 명단 ({len(df_public)}명)")
                if '입금' not in df_public.columns: df_public['입금'] = "X"
                st.markdown(render_applicant_list_html(df_public), unsafe_allow_html=True)

            with col_stats:
                st.markdown("##### 📌 요약 정보")
                with st.container(border=True):
                    st.write(f"- **총 신청 인원**: {len(df_public)}명")
                    if not is_expired and not is_full:
                        diff = deadline_dt - now
                        st.caption(f"마감까지 {diff.seconds // 3600 + (diff.days * 24)}시간 {(diff.seconds % 3600) // 60}분 전")
        else:
            st.info("👋 **아직 신청자가 없습니다.** 첫 번째 참가자가 되어보세요!")
            st.metric("현재 참가 인원", "0명")

# --- 탭 2: 라인업 공개 ---
with tab2:
    log_visit("라인업조회", st.session_state.get('my_name', '익명'))
    if not current_game or current_game.get('제목') == 'CLOSED':
        st.header("📋 이번 주 라인업")
        st.info("💤 **현재 진행 중인 게임이 없습니다.**\n새로운 게임이 개설되고 팀 배정이 완료되면 이곳에 라인업이 공개됩니다.")
    else:
        is_visible = str(current_game.get('공개여부', 'X')).upper().strip() == 'O'
        if not is_visible:
            st.header("📋 이번 주 라인업")
            st.divider()
            st.warning("🔒 **운영진이 라인업을 최종 점검 중입니다.**")
            st.markdown("### ⏳ 잠시만 기다려주세요!\n- 현재 신청 마감 후 **팀 밸런스 조정 및 검토**를 진행하고 있습니다.\n- 검토가 완료되면 이곳에 라인업이 공개됩니다.")
            st.markdown("<div style='text-align: center; font-size: 80px; margin-top: 20px;'>🕵️‍♂️</div>", unsafe_allow_html=True)
        else:
            with st.expander("📘 이용 가이드: 배정 기준 및 보는 법", expanded=False):
                st.markdown("""**1. 배정 기준 (우선순위 점수제)**\n| 항목 | 점수 | 설명 |\n| :--- | :--- | :--- |\n| **기본 점수** | `50점` | 모든 참가자 기본 지급 |\n| **1순위 배정** | `-10점`/회 | 오늘 1순위를 많이 할수록 **배정 누적**되어 양보 유도 |\n| **기여도** | `+3~10점` | **대기/비선호 포지션** 수행 시 점수 적립 |""")

            st.header("📋 이번 주 라인업")
            data_final = load_applicants()
            if not data_final: st.info("확정 전")
            else:
                df_final = pd.DataFrame(data_final)
                round_score_db, d_hist, d_hard = {}, {p['이름']: 0 for p in df_final.to_dict('records')}, {p['이름']: 0 for p in df_final.to_dict('records')}
                
                for r in range(1, 5):
                    round_score_db[r] = {}
                    col_pos = f"확정{r}"
                    for _, row in df_final.iterrows():
                        nm = row['이름']
                        sc, reason_val = get_priority_score(row.to_dict(), d_hist, d_hard)
                        round_score_db[r][nm] = {'score': sc, 'reason': reason_val}
                    
                    if col_pos in df_final.columns:
                        for _, row in df_final.iterrows():
                            nm = row['이름']
                            assigned = str(row.get(col_pos, '')).strip()
                            if not assigned: continue
                            w1, w2, w3 = str(row.get('1순위', '')).strip(), str(row.get('2순위', '')).strip(), str(row.get('3순위', '')).strip()
                            match_type = 'random'
                            if assigned == '대기': match_type = 'wait'
                            elif assigned == w1: match_type = '1st'
                            elif assigned == w2: match_type = '2nd'
                            elif assigned == w3: match_type = '3rd'
                            
                            if match_type == '1st': d_hist[nm] += 1
                            pts = 10 if match_type == 'wait' else 5 if match_type == '3rd' else 3 if match_type == '2nd' else 5 if (match_type == 'random' and w1 and w2 and w3 and w1!='선택 안함' and w2!='선택 안함' and w3!='선택 안함') else 3 if match_type == 'random' else 0
                            if pts > 0: d_hard[nm] += pts

                df_final['이름_masked'] = df_final['이름'].apply(anonymize_name)
                if '이름' in df_final.columns and '연락처' in df_final.columns:
                    df_final = df_final.drop_duplicates(subset=['이름', '연락처'], keep='last')
                
                st.divider()
                lineup_tabs = st.tabs(["1·2 세트", "3·4 세트", "5·6 세트", "7·8 세트"])
                
                for i, (col_team, col_pos) in enumerate([("팀1", "확정1"), ("팀2", "확정2"), ("팀3", "확정3"), ("팀4", "확정4")], 1):
                    with lineup_tabs[i-1]:
                        if col_pos in df_final.columns and col_team in df_final.columns:
                            playing = df_final[df_final[col_pos].astype(str).str.strip() != '']
                            if not playing.empty:
                                real_players = playing[playing[col_pos] != "대기"]
                                if not real_players.empty:
                                    team_a_df = real_players[real_players[col_team]=="A팀"]
                                    team_b_df = real_players[real_players[col_team]=="B팀"]
                                    count_a, count_b = len(team_a_df), len(team_b_df)
                                    
                                    def get_missing_pos(df_team, pos_col):
                                        if df_team.empty: return []
                                        missing = list(set(POSITIONS_ALL) - set(df_team[pos_col].unique()))
                                        sort_order = {p: idx for idx, p in enumerate(POSITIONS_ALL)}
                                        missing.sort(key=lambda x: sort_order.get(x, 99))
                                        return missing

                                    missing_a, missing_b = get_missing_pos(team_a_df, col_pos), get_missing_pos(team_b_df, col_pos)
                                    missing_text_a = ", ".join(missing_a) if missing_a else "없음"
                                    missing_text_b = ", ".join(missing_b) if missing_b else "없음"

                                    info_msg = f"📢 **[{i*2-1}·{i*2}세트] {count_a} vs {count_b} 경기**"
                                    if count_a != count_b: info_msg += f" (🔴A제외: {missing_text_a} | 🔵B제외: {missing_text_b})"
                                    else: info_msg += f" (공통 제외: {missing_text_a})" if missing_text_a == missing_text_b else f" (🔴A제외: {missing_text_a} | 🔵B제외: {missing_text_b})"
                                    st.info(info_msg)

                                    st.markdown("### 🏟️ Court View")
                                    st.markdown(render_tactical_board(team_a_df, "A팀", col_pos, round_score_db, i), unsafe_allow_html=True)
                                    st.markdown("<div style='text-align: center; font-weight: bold; margin: 5px 0; color: #999; font-size: 0.8em;'>▼ NEXT COURT ▼</div>", unsafe_allow_html=True)
                                    st.markdown(render_tactical_board(team_b_df, "B팀", col_pos, round_score_db, i), unsafe_allow_html=True)
                                
                                bench = playing[playing[col_pos]=="대기"]
                                if not bench.empty:
                                    st.divider()
                                    st.caption(f"🛌 **대기 선수 (다음 세트 출전 1순위)**")
                                    cols = st.columns(len(bench)) if len(bench) > 0 else []
                                    for idx, (_, r) in enumerate(bench.iterrows()):
                                        sc = round_score_db[i][r['이름']]['score'] if i in round_score_db and r['이름'] in round_score_db[i] else 0
                                        if idx < len(cols):
                                            with cols[idx]:
                                                st.markdown(f"""<div style="text-align: center; background: #f9f9f9; border: 1px solid #eee; border-radius: 8px; padding: 8px;"><div style="font-weight: bold; font-size: 0.9em; color: #333; margin-bottom: 2px;">{r['이름_masked']}</div><div style="font-size: 0.75em; color: #666; margin-bottom: 2px;">(희망: {r.get('1순위', '-')})</div><div style="font-size: 0.8em; color: #1976D2; font-weight: bold;">{sc:.2f}</div></div>""", unsafe_allow_html=True)
                        else:
                            st.warning("아직 배정 정보가 없습니다.")

# --- 탭 3: My Page ---
with tab3:
    with st.expander("📘 이용 가이드: 내 정보 확인", expanded=False):
        st.write("본인의 이름과 연락처를 입력하면 '나만의 선수 카드'와 '과거 기록'을 확인할 수 있습니다.")

    st.header("📊 My Player Card")
    if 'my_name' not in st.session_state: st.session_state['my_name'] = ""
    if 'my_phone' not in st.session_state: st.session_state['my_phone'] = ""

    with st.form("my_history"):
        c1, c2 = st.columns(2)
        with c1: input_name = st.text_input("이름", value=st.session_state['my_name'])
        with c2: input_phone = st.text_input("연락처", value=st.session_state['my_phone'])
        if st.form_submit_button("조회 & 분석"):
            st.session_state['my_name'] = input_name
            st.session_state['my_phone'] = input_phone
            st.toast(f"{input_name}님 기록을 조회합니다.", icon="🔍")

    if st.session_state['my_name'] and st.session_state['my_phone']:
        my_name, my_phone = st.session_state['my_name'], st.session_state['my_phone']
        clean_phone = normalize_phone(my_phone)
        
        hist = get_my_history(my_name, my_phone)
        mvp_received, mvp_voted = get_my_mvp_stats(my_name, my_phone)
        cur_apps = load_applicants()
        my_cur = [p for p in cur_apps if p['이름']==my_name and normalize_phone(p['연락처'])==clean_phone]
        
        score_part = min(len(hist) * 5, 100)
        score_manner = min(mvp_received * 10, 100)
        unique_pos = set([str(h.get('1순위', '')).strip() for h in hist if h.get('1순위')])
        score_div = min(len(unique_pos) * 15, 100)
        score_social = min(mvp_voted * 5, 100)
        
        dedication_count = sum(2 if str(h.get('확정포지션', '')).strip() == '대기' else 1 for h in hist if str(h.get('확정포지션', '')).strip() and str(h.get('확정포지션', '')).strip() != str(h.get('1순위', '')).strip())
        score_dedic = min(dedication_count * 15, 100) 

        stats = {'participation': score_part, 'manner': score_manner, 'dedication': score_dedic, 'diversity': score_div, 'social': score_social}

        st.divider()
        col_chart, col_info = st.columns([1.2, 1])
        
        with col_chart:
            st.markdown(f"### 🏐 {my_name}님의 스탯")
            try: st.plotly_chart(draw_radar_chart(stats), use_container_width=True, config={'staticPlot': True})
            except: st.error("차트 로딩 중 오류가 발생했습니다.")
            
            with st.expander("ℹ️ 스탯(능력치) 산정 기준 보기"):
                st.markdown("<div style='font-size: 0.9em; color: #555;'>- **🔥 참여율**: 꾸준함의 상징! (총 참여 20회 시 만점)<br>- **✨ 매너**: 동료들의 인정! (MVP 수상 10회 시 만점)<br>- **❤️ 헌신**: 팀을 위한 양보! (비선호 포지션/대기 수행 시 상승)<br>- **🌈 다양성**: 올라운더 플레이어! (경험한 포지션 수에 비례)<br>- **🤝 사교성**: 커뮤니티 관심도! (MVP 투표 참여 20회 시 만점)</div>", unsafe_allow_html=True)
            
        with col_info:
            st.markdown("#### 📌 요약 리포트")
            st.write(f"- **총 참여**: {len(hist)}회\n- **MVP 수상**: {mvp_received}회\n- **포지션 경험**: {len(unique_pos)}개\n- **팀을 위한 헌신**: {dedication_count} 포인트")
            if my_cur: st.info(f"이번 주: **{'✅ 참가확인' if str(my_cur[0].get('입금')).upper() == 'O' else '⏳ 입금확인중'}**")
            else: st.caption("이번 주 신청 내역이 없습니다.")

        with st.expander("📜 과거 경기 기록 전체 보기"):
            if hist:
                df_hist = pd.DataFrame(hist)
                valid_cols = [c for c in ['일시', '게임제목', '1순위', '레벨', '확정포지션'] if c in df_hist.columns]
                st.dataframe(df_hist[valid_cols], hide_index=True, use_container_width=True)
            else: st.info("아직 기록된 경기가 없습니다.")

# --- 탭 4: MVP ---
with tab4:
    with st.expander("📘 이용 가이드: MVP 투표", expanded=False):
        st.write("🔒 본인 인증 후, 경기 내용을 떠올리며 가장 인상 깊었던 선수에게 투표해주세요.")

    st.header("🏆 MVP 투표")
    apps = load_applicants()
    is_archived = False
    
    if not apps:
        all_history = load_all_history()
        if all_history:
            last_date = all_history[-1].get('일시')
            temp_players = { (h.get('이름'), h.get('연락처')): h for h in all_history if h.get('일시') == last_date }
            if temp_players:
                apps = list(temp_players.values())
                is_archived = True
                st.info(f"📢 지난 게임 **({last_date})** 명단으로 투표를 진행합니다.")

    if not apps:
        st.warning("투표할 대상이 없습니다.")
    else:
        if not st.session_state['mvp_voter_verified']:
            with st.form("mvp_auth"):
                st.info("🔒 투표를 위해 본인 인증을 해주세요.")
                c1, c2 = st.columns(2)
                with c1: voter = st.text_input("이름")
                with c2: vphone = st.text_input("연락처")
                if st.form_submit_button("인증하기"):
                    clean_vphone = normalize_phone(vphone)
                    found = any(str(p['이름']).strip() == voter and normalize_phone(p['연락처']) == clean_vphone for p in apps)
                    if found:
                        st.session_state.update({'mvp_voter_verified': True, 'mvp_voter_name': voter, 'mvp_voter_phone': clean_vphone})
                        st.rerun()
                    else: st.error("명단에 없는 정보입니다.")
        else:
            st.success(f"👋 안녕하세요, **{st.session_state['mvp_voter_name']}**님! 오늘의 MVP는 누구인가요?")
            
            def process_vote(candidate_name):
                suc, msg = save_mvp_vote(st.session_state['mvp_voter_name'], st.session_state['mvp_voter_phone'], candidate_name)
                if suc: 
                    st.toast(f"🎉 {candidate_name}님에게 투표했습니다!", icon="🗳️"); time.sleep(1); st.rerun()
                else: st.error(msg)

            df_vote = pd.DataFrame(apps)
            
            if not is_archived and '확정1' in df_vote.columns and df_vote['확정1'].astype(str).str.strip().any():
                st.markdown("### 🏟️ 라인업을 보며 투표하기")
                st.caption("각 세트별 활약상을 떠올려보세요! (이름 옆 버튼 클릭)")
                tabs = st.tabs(["1·2 세트", "3·4 세트", "5·6 세트"])
                for i, tab in enumerate(tabs):
                    with tab:
                        col_pos, col_team = f"확정{i+1}", f"팀{i+1}"
                        playing = df_vote[df_vote[col_pos].astype(str).str.strip() != '']
                        if playing.empty:
                            st.info("이 세트의 배정 정보가 없습니다.")
                            continue
                            
                        c1, c2 = st.columns(2)
                        with c1:
                            st.error("🔴 A팀")
                            for _, r in playing[(playing[col_team]=="A팀") & (playing[col_pos]!="대기")].iterrows():
                                b_col1, b_col2 = st.columns([3, 1])
                                with b_col1: st.write(f"**{r[col_pos]}**: {r['이름']}")
                                with b_col2: 
                                    if st.button("투표", key=f"v_a_{i}_{r['이름']}"): process_vote(r['이름'])
                        with c2:
                            st.info("🔵 B팀")
                            for _, r in playing[(playing[col_team]=="B팀") & (playing[col_pos]!="대기")].iterrows():
                                b_col1, b_col2 = st.columns([3, 1])
                                with b_col1: st.write(f"**{r[col_pos]}**: {r['이름']}")
                                with b_col2: 
                                    if st.button("투표", key=f"v_b_{i}_{r['이름']}"): process_vote(r['이름'])
            else:
                st.markdown("### 👥 전체 참가자 명단")
                for idx, row in df_vote.iterrows():
                    with st.container():
                        lc1, lc2, lc3 = st.columns([2, 2, 1])
                        with lc1: st.write(f"**{row['이름']}**")
                        with lc2: st.caption(f"포지션: {row.get('확정포지션') or row.get('1순위') or '-'}")
                        with lc3: 
                            if st.button("투표", key=f"v_list_{idx}"): process_vote(row['이름'])
                        st.markdown("<hr style='margin: 5px 0;'>", unsafe_allow_html=True)

            st.divider()
            if st.button("로그아웃 (다른 사람 투표)"):
                st.session_state['mvp_voter_verified'] = False
                st.rerun()

            st.subheader("📊 실시간 득표 현황 (Top 5)")
            rank = get_mvp_ranking_today()
            if not rank.empty: 
                top1 = rank.iloc[0]
                if top1['득표수'] > 0: st.markdown(f"🥇 **1위: {top1['이름']} ({top1['득표수']}표)**")
                st.dataframe(rank.head(5), hide_index=True, use_container_width=True)
            else: st.info("아직 투표가 없습니다.")

            with st.expander("👑 명예의 전당 보기"):
                hof = get_mvp_hall_of_fame()
                if len(hof)>0: 
                    if 'MVP후보' in hof.columns: hof = hof.rename(columns={'MVP후보':'MVP', '일시':'날짜'})
                    st.dataframe(hof[['날짜','MVP','득표수']], hide_index=True, use_container_width=True)

# --- 탭 8: 경기 영상 ---
with tab8:
    st.header("📺 경기 영상 & 하이라이트")
    YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@pickup-game-y7r" 
    
    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown("### 📢 우리들의 멋진 플레이를 다시 보세요!")
            st.write("매주 경기 영상과 하이라이트가 업로드됩니다.")
        with c2:
            st.link_button("👉 유튜브 채널 바로가기", YOUTUBE_CHANNEL_URL, use_container_width=True)

    st.divider()
    video_data = get_latest_video()
    if video_data and 'url' in video_data and video_data['url']:
        st.subheader(f"🎬 {video_data.get('title', '최신 하이라이트')}")
        st.caption(f"등록일: {video_data.get('date', '')}")
        try: st.video(video_data['url'])
        except: st.error("영상을 불러올 수 없습니다. 링크를 확인해주세요.")
    else:
        st.info("아직 등록된 하이라이트 영상이 없습니다.")

# --- 탭 5: 소리함 ---
with tab5:
    st.header("🗣️ 소리함 (Q&A)")
    with st.expander("📝 건의사항 남기기 (클릭)", expanded=False):
        st.caption("익명으로 운영되며, 건전한 소통을 위해 예쁜 말을 사용해주세요.")
        with st.form("suggestion_box"):
            msg = st.text_area("내용을 입력하세요", height=100)
            if st.form_submit_button("등록하기", type="primary"):
                if msg:
                    if save_suggestion(msg): 
                        st.success("등록되었습니다! 아래 게시판에서 확인하세요."); time.sleep(1); st.rerun()
                    else: st.error("전송 실패")
                else: st.warning("내용을 입력해주세요.")

    st.divider()
    st.subheader("📋 건의 & 답변 게시판")
    data = load_suggestions()
    if data:
        df = pd.DataFrame(data)
        if '상태' not in df.columns: df['상태'] = '대기중'
        if '답변' not in df.columns: df['답변'] = ''
        df = df.sort_index(ascending=False)

        for _, row in df.iterrows():
            status = row.get('상태', '대기중')
            reply = row.get('답변', '')
            badge_color = "green" if status == "완료" else "orange"

            with st.container(border=True):
                c1, c2 = st.columns([0.8, 4])
                with c1:
                    st.caption(row['일시'][:10]) 
                    st.markdown(f":{badge_color}[**{status}**]")
                with c2:
                    st.write(f"**Q.** {row['내용']}")
                    if reply and str(reply).strip(): st.info(f"**A.** {reply}", icon="💬")
    else:
        st.info("아직 등록된 건의사항이 없습니다.")

# --- 탭 6: 라인업 생성 (관리자) ---
with tab6:
    st.header("⚡ 공평 라인업 생성")
    if not st.session_state.get('admin_logged_in', False):
        st.warning("⚠️ 관리자 권한이 필요한 메뉴입니다.")
        with st.form("lineup_login_form"):
            pw = st.text_input("비밀번호", type="password")
            keep_login = st.checkbox("로그인 상태 유지하기 (체크 필수)", value=True)
            if st.form_submit_button("관리자 로그인"):
                if pw == ADMIN_PASSWORD:
                    st.session_state['admin_logged_in'] = True
                    st.toast("관리자 인증 성공!", icon="⚡")
                    if keep_login: st.query_params["auth"] = ADMIN_PASSWORD
                    st.rerun()
                else: st.error("비밀번호가 일치하지 않습니다.")
    else:
        c_info, c_logout = st.columns([4, 1])
        with c_info: st.info("🔓 관리자 권한으로 접속 중입니다.")
        with c_logout:
            if st.button("로그아웃", key="logout_tab6"):
                st.session_state['admin_logged_in'] = False
                st.query_params.clear()
                st.rerun()

        with st.expander("ℹ️ 점수 계산 규칙 (컨닝페이퍼)", expanded=False):
            st.markdown("| 항목 | 점수 | 설명 |\n| :--- | :--- | :--- |\n| **기본 점수** | `50점` | 모든 참가자 기본 지급 |\n| **1순위 배정** | `-10점`/회 | 오늘 1순위를 많이 할수록 **배정 누적**되어 양보 유도 |\n| **기여도** | **누적** | **한번 얻은 점수는 사라지지 않음!** |")

        data = load_applicants()
        if not data: st.warning("참가자가 없습니다.")
        else:
            df = pd.DataFrame(data)
            with st.expander("💬 카카오톡 공유 텍스트 생성 (클릭)"):
                try: st.code(generate_kakao_text(df), language="text")
                except: st.error("텍스트 생성 오류")
            
            st.divider()
            
            col_gen, col_refresh = st.columns([3, 1])
            with col_gen:
                if st.button("🚀 공평 라인업 자동 생성 (스네이크 방식)", type="primary", use_container_width=True):
                    with st.spinner("최적의 밸런스를 계산 중입니다..."): 
                        df_clean = df.copy()
                        cols_to_clean = []
                        for i in range(1, 5): cols_to_clean.extend([f"팀{i}", f"확정{i}"])
                        for col in cols_to_clean:
                            if col in df_clean.columns: df_clean[col] = ""
                        
                        st.session_state['fair_results'] = generate_priority_schedule(df_clean)
                        st.success("생성 완료! 아래에서 확인 후 '저장'하세요.")
            
            with col_refresh:
                if st.button("🔄 시각화 새로고침", use_container_width=True):
                    if 'fair_results' in st.session_state: del st.session_state['fair_results']
                    st.rerun()

            if 'fair_results' not in st.session_state and '확정1' in df.columns:
                if df['확정1'].astype(str).str.strip().any():
                    try:
                        restored_results = {}
                        base_players = df.to_dict('records')
                        d_hist, d_hard = {p['이름']: 0 for p in base_players}, {p['이름']: 0 for p in base_players}
                        for r in range(1, 5):
                            col_team, col_pos = f"팀{r}", f"확정{r}"
                            team_a, team_b = [], []
                            score_map = {p['이름']: get_priority_score(p, d_hist, d_hard) for p in base_players}

                            for _, row in df.iterrows():
                                p_name, assigned, team_val = row['이름'], str(row.get(col_pos, '')).strip(), str(row.get(col_team, '')).strip()
                                if not assigned: continue
                                
                                p_data = row.to_dict()
                                p_data['assigned_pos'] = assigned
                                if p_name in score_map:
                                    p_data['priority_score'], p_data['score_reason'] = score_map[p_name]
                                
                                w1, w2, w3 = str(p_data.get('1순위','')).strip(), str(p_data.get('2순위','')).strip(), str(p_data.get('3순위','')).strip()
                                match_type = 'wait' if assigned == '대기' else '1st' if assigned == w1 else '2nd' if assigned == w2 else '3rd' if assigned == w3 else 'random'
                                
                                if team_val == "A팀": team_a.append(p_data)
                                elif team_val == "B팀" or assigned == "대기": team_b.append(p_data)

                                if match_type == '1st': d_hist[p_name] += 1
                                if match_type == 'wait': d_hard[p_name] += 10
                                elif match_type in ['3rd', 'random']: d_hard[p_name] += 5
                                elif match_type == '2nd': d_hard[p_name] += 3

                            restored_results[r] = (team_a, team_b)
                        st.session_state['fair_results'] = restored_results
                    except Exception as e: st.error(f"데이터 복구 중 오류: {e}")

            if 'fair_results' in st.session_state:
                schedule_map = {name: {} for name in df['이름']}
                for r_num, (team_a, team_b) in st.session_state['fair_results'].items():
                    for p in team_a: 
                        if p['이름'] in schedule_map:
                            schedule_map[p['이름']][f"확정{r_num}"] = p['assigned_pos']
                            schedule_map[p['이름']][f"팀{r_num}"] = "A팀"
                    for p in team_b: 
                        if p['이름'] in schedule_map:
                            schedule_map[p['이름']][f"확정{r_num}"] = p['assigned_pos']
                            schedule_map[p['이름']][f"팀{r_num}"] = "B팀"
                
                for idx, row in df.iterrows():
                    name = row['이름']
                    if name in schedule_map:
                        for r in range(1, 5): 
                            df.at[idx, f'확정{r}'] = schedule_map[name].get(f'확정{r}', '')
                            df.at[idx, f'팀{r}'] = schedule_map[name].get(f'팀{r}', '')
                
                r_tabs = st.tabs(["1·2 세트", "3·4 세트", "5·6 세트", "7·8 세트"])
                for i, tab in enumerate(r_tabs, 1):
                    with tab:
                        team_a, team_b = st.session_state['fair_results'][i]
                        valid_team_a = [p for p in team_a if p['이름'] in schedule_map]
                        valid_team_b = [p for p in team_b if p['이름'] in schedule_map]
                        
                        count_a = len([p for p in valid_team_a if p['assigned_pos'] != "대기"])
                        count_b = len([p for p in valid_team_b if p['assigned_pos'] != "대기"])
                        
                        def calculate_team_sum(team_list):
                            total = 0
                            for p in team_list:
                                if p['assigned_pos'] != "대기":
                                    total += LEVEL_MAP.get(str(p.get('레벨', '입문')).split(" ")[0], 1)
                            return total
                        sum_a, sum_b = calculate_team_sum(valid_team_a), calculate_team_sum(valid_team_b)

                        def get_missing_pos_list(player_list):
                            current_pos = set()
                            for p in player_list:
                                if p.get('assigned_pos') and p['assigned_pos'] != "대기": current_pos.add(p['assigned_pos'])
                            return list(set(POSITIONS_ALL) - current_pos)
                        
                        miss_a, miss_b = get_missing_pos_list(valid_team_a), get_missing_pos_list(valid_team_b)
                        miss_txt_a = ", ".join(miss_a) if miss_a else "없음"
                        miss_txt_b = ", ".join(miss_b) if miss_b else "없음"

                        st.info(f"📢 **[{i*2-1}·{i*2}세트] {count_a} vs {count_b}** (🔴A제외: {miss_txt_a} | 🔵B제외: {miss_txt_b})")
                        
                        b_col1, b_col2 = st.columns([1, 4])
                        with b_col1:
                            diff = sum_a - sum_b
                            st.metric("🔴 A팀 전력", f"{sum_a}", delta=f"격차: {diff}", delta_color="normal" if abs(diff) <= 2 else "inverse")
                        with b_col2:
                            max_possible = max(count_a, count_b) * 5 if max(count_a, count_b) > 0 else 1
                            st.caption(f"전력 밸런스: A팀({sum_a}) vs B팀({sum_b})")
                            st.progress(min(sum_a / max_possible, 1.0))
                            st.progress(min(sum_b / max_possible, 1.0))

                        st.markdown("### 🏟️ Court View")
                        df_a, df_b = pd.DataFrame(valid_team_a), pd.DataFrame(valid_team_b)
                        st.markdown(render_tactical_board(df_a, "A팀", "assigned_pos"), unsafe_allow_html=True)
                        st.markdown("<div style='text-align: center; font-weight: bold; margin: 5px 0; color: #999; font-size: 0.8em;'>▼ NEXT COURT ▼</div>", unsafe_allow_html=True)
                        st.markdown(render_tactical_board(df_b, "B팀", "assigned_pos"), unsafe_allow_html=True)
                        
                        bench = [p for p in valid_team_a+valid_team_b if p['assigned_pos']=="대기"]
                        if bench:
                            st.divider()
                            st.caption("🛌 **대기 인원**")
                            for p in bench:
                                st.write(f"- {p['이름']} (희망: {p.get('1순위', '-')})")
                                st.markdown(format_score_html(p.get('priority_score', 0), p.get('score_reason', '')), unsafe_allow_html=True)

            st.divider()
            st.subheader("🛠️ 결과 수정 및 확정")
            st.warning("수정 후 반드시 '저장' 버튼을 눌러야 일반 사용자에게 공개됩니다.")
            
            cols = ["이름", "레벨", "1순위", "팀1", "확정1", "팀2", "확정2", "팀3", "확정3", "팀4", "확정4", "비고"]
            valid_cols = [c for c in cols if c in df.columns]
            edited_df = st.data_editor(df[valid_cols], hide_index=True, num_rows="dynamic")
            
            if st.button("💾 저장 (공개)", type="primary"):
                final_df = df.copy()
                final_df.update(edited_df)
                update_lineup(final_df)
                if 'fair_results' in st.session_state: del st.session_state['fair_results']
                st.success("저장되었습니다! 화면이 갱신됩니다."); time.sleep(1.0); st.rerun()

# --- 탭 7: 관리자 ---
with tab7:
    st.header("⚙️ 관리자 페이지")
    admin_auth = st.empty()

    if not st.session_state.get('admin_logged_in', False):
        with admin_auth.form("admin_main_login_unique"): 
            pw = st.text_input("비밀번호", type="password")
            keep_login = st.checkbox("로그인 상태 유지하기 (체크 필수)", value=True)
            if st.form_submit_button("확인"):
                if pw == ADMIN_PASSWORD:
                    st.session_state['admin_logged_in'] = True
                    st.toast("관리자 모드 접속", icon="🔓")
                    if keep_login: st.query_params["auth"] = ADMIN_PASSWORD
                    admin_auth.empty()
                    st.rerun()
                else: st.error("비밀번호가 일치하지 않습니다.")
    
    if st.session_state.get('admin_logged_in', False):
        if st.button("로그아웃 (도장 지우기)", key="logout_tab7"):
            st.session_state['admin_logged_in'] = False
            st.query_params.clear()
            st.rerun()

        st.subheader("📊 오늘의 접속 현황")
        sheet_log = get_sheet_instance(SHEET_LOGS)
        if sheet_log:
            try:
                rows = sheet_log.get_all_values()
                if not rows: st.info("오늘 방문자가 아직 없습니다.")
                else:
                    df_log = pd.DataFrame(rows)
                    if len(df_log.columns) >= 4:
                        df_log = df_log.iloc[:, :4] 
                        df_log.columns = ["일시", "유형", "접속자(추정)", "IP주소"] 
                    if str(df_log.iloc[0]['일시']) == "일시": df_log = df_log.iloc[1:] 

                    if '일시' in df_log.columns:
                        now_kst = datetime.utcnow() + timedelta(hours=9)
                        today_str = now_kst.strftime("%Y-%m-%d")
                        df_log['날짜'] = df_log['일시'].astype(str).apply(lambda x: x.split(" ")[0])
                        df_today = df_log[df_log['날짜'] == today_str]
                        
                        visit_count = len(df_today[df_today['유형'] == '메인접속'])
                        lineup_count = len(df_today[df_today['유형'] == '라인업조회'])
                        
                        m1, m2 = st.columns(2)
                        m1.metric("오늘 방문자", f"{visit_count}명")
                        m2.metric("라인업 조회", f"{lineup_count}회")
                        
                        with st.expander("📜 상세 접속 로그 보기"):
                            st.dataframe(df_today[["일시", "유형", "접속자(추정)", "IP주소"]], hide_index=True)
            except Exception as e: st.error(f"통계 로딩 실패: {e}")

        st.divider()

        st.subheader("📢 라인업 공개 설정")
        if current_game:
            is_visible_now = str(current_game.get('공개여부', 'X')).upper().strip() == 'O'
            c_tog, c_stat = st.columns([1, 3])
            with c_tog: toggle_val = st.toggle("라인업 공개하기", value=is_visible_now)
            with c_stat:
                if toggle_val: st.success("🟢 **공개 중**")
                else: st.error("🔒 **비공개**")

            if toggle_val != is_visible_now:
                if toggle_game_visibility(toggle_val): st.rerun()
        else: st.warning("진행 중인 게임 없음")

        st.divider()

        st.subheader("✅ 참가자 확정 및 입금 관리")
        apps = load_applicants()
        
        if apps:
            df_manage = pd.DataFrame(apps)
            if '입금' not in df_manage.columns: df_manage['입금'] = 'X'
            if '참가여부' not in df_manage.columns: df_manage['참가여부'] = 'O'
            
            df_manage['입금_bool'] = df_manage['입금'].apply(lambda x: True if str(x).upper()=='O' else False)
            df_manage['참가_bool'] = df_manage['참가여부'].apply(lambda x: False if str(x).upper()=='X' else True) 
            
            df_manage = df_manage.reset_index(drop=True)
            
            # [공평 시스템] 특정 팀 우대 조건 제거, 오직 정원순으로만 자름
            mask_capa = (df_manage.index < MAX_CAPACITY)
            df_confirmed = df_manage[mask_capa]
            df_waiting = df_manage[~mask_capa]

            with st.form("deposit_check_form"):
                st.caption("💡 **참가**: 체크 해제하면 라인업에서 제외됩니다. (대기자가 자동으로 올라옵니다)")
                st.caption("💡 **입금**: 입금 확인 시 체크하세요.")
                
                col_config = {
                    "참가_bool": st.column_config.CheckboxColumn("참가", help="체크 해제 시 불참/제외 처리", default=True),
                    "입금_bool": st.column_config.CheckboxColumn("입금", help="입금 확인", default=False),
                    "이름": st.column_config.TextColumn("이름", disabled=True),
                    "1순위": st.column_config.TextColumn("1순위", disabled=True),
                }
                
                st.success(f"📌 **확정 대상 ({len(df_confirmed)}명)**")
                ed_conf = st.data_editor(
                    df_confirmed[["참가_bool", "이름", "연락처", "입금_bool", "1순위", "비고"]], 
                    hide_index=True, key="ed_conf", column_config=col_config, use_container_width=True
                )
                
                if not df_waiting.empty:
                    st.warning(f"⏳ **대기 대상 ({len(df_waiting)}명)**")
                    ed_wait = st.data_editor(
                        df_waiting[["참가_bool", "이름", "연락처", "입금_bool", "1순위", "비고"]], 
                        hide_index=True, key="ed_wait", column_config=col_config, use_container_width=True
                    )
                else: ed_wait = pd.DataFrame()

                st.divider()
                if st.form_submit_button("💾 일괄 저장하기", type="primary"):
                    for i, r in ed_conf.iterrows(): 
                        df_manage.loc[r.name, '입금_bool'] = r['입금_bool']
                        df_manage.loc[r.name, '참가_bool'] = r['참가_bool']
                        df_manage.loc[r.name, '비고'] = r['비고']
                    
                    if not df_waiting.empty and not ed_wait.empty:
                        for i, r in ed_wait.iterrows(): 
                            df_manage.loc[r.name, '입금_bool'] = r['입금_bool']
                            df_manage.loc[r.name, '참가_bool'] = r['참가_bool']
                            df_manage.loc[r.name, '비고'] = r['비고']
                    
                    df_manage['입금'] = df_manage['입금_bool'].apply(lambda x: 'O' if x else 'X')
                    df_manage['참가여부'] = df_manage['참가_bool'].apply(lambda x: 'O' if x else 'X')
                    update_lineup(df_manage)
                    st.success("✅ 저장되었습니다! (불참자는 라인업 생성 시 자동 제외됩니다)"); time.sleep(0.5); st.rerun()

            st.divider()
            st.markdown("### 💬 안내 문자 생성기")
            if current_game:
                game_date_raw = str(current_game.get('일시', ''))
                formatted_date = game_date_raw 
                try:
                    match = re.search(r'\d{4}-\d{2}-\d{2}', game_date_raw)
                    if match:
                        dt_obj = datetime.strptime(match.group(), "%Y-%m-%d")
                        formatted_date = f"{dt_obj.month}월 {dt_obj.day}일"
                except: pass
                
                mc1, mc2, mc3 = st.columns(3)
                with mc1:
                    with st.expander("📢 운동 안내", expanded=False):
                        msg1 = f"[여순광배구]\n금일({formatted_date}) 18:00 운동 예정.\n라인업 확인 바랍니다.\nhttps://volleyball-pickup.streamlit.app/"
                        st.code(msg1, language="text")
                with mc2:
                    with st.expander("🚫 정원 초과 안내", expanded=False):
                        if not df_waiting.empty: st.caption(f"대상: {', '.join(df_waiting['이름'].tolist())}")
                        else: st.caption("현재 대기자가 없습니다.")
                        msg2 = f"[여순광배구]\n죄송합니다. 금일({formatted_date}) 정원 초과로 참여가 어렵습니다.\n결원 발생 시 순서대로 연락드리겠습니다!\n다음에 꼭 함께해요! 🏐"
                        st.code(msg2, language="text")
                with mc3:
                    with st.expander("🏆 MVP 투표 독려", expanded=False):
                        msg3 = f"[여순광배구]\n오늘 운동 즐거우셨나요? 🏐\n오늘의 MVP에게 투표해주세요!\n\n👉 투표하러 가기:\nhttps://volleyball-pickup.streamlit.app/"
                        st.code(msg3, language="text")
            else: st.warning("진행 중인 게임 정보가 없습니다.")
        else: st.info("신청자 없음")

        st.divider()
        st.subheader("🛠️ 게임 관리")
        tab_new, tab_close = st.tabs(["🆕 새 게임", "🏁 종료"])
        
        with tab_new:
            with st.form("create_game_full"):
                st.caption("새로운 게임을 만들면 기존 명단은 자동으로 '지난 기록'으로 저장됩니다.")
                reset_chk = st.checkbox("기존 명단 초기화 (필수)", value=True)
                
                c_info1, c_info2 = st.columns(2)
                with c_info1:
                    title = st.text_input("게임 제목", placeholder="X월 X일 정기모임")
                    dt = st.text_input("일시", placeholder="YYYY-MM-DD HH:MM")
                    loc = st.text_input("장소", value="순천조례초 체육관")
                    gender = st.radio("성별", ["혼성", "남자", "여자"], horizontal=True)
                with c_info2:
                    dead_date = st.date_input("마감 날짜")
                    dead_time = st.time_input("마감 시간")
                    fee = st.text_input("참가비", value="5,000원")
                    acc = st.text_input("계좌", placeholder="카카오뱅크 xxx-xxxx")
                
                desc = st.text_area("공지사항/설명")
                contact = st.text_input("문의 연락처")

                if st.form_submit_button("개설하기"):
                    if reset_chk:
                        archive_current_game(); clear_applicants()
                    deadline_str = f"{dead_date} {dead_time.strftime('%H:%M')}"
                    info = {"제목": title, "일시": dt, "장소": loc, "성별": gender, "참가비": fee, "계좌": acc, "설명": desc, "연락처": contact, "마감일시": deadline_str}
                    save_game_info(info)
                    st.success("새 게임이 개설되었습니다!"); time.sleep(1.0); st.rerun()

        with tab_close:
            st.warning("게임을 종료하면 '모집 마감' 상태가 되며, 명단은 그대로 유지됩니다.")
            if st.button("현재 게임 종료하기 (CLOSED)"):
                archive_current_game()
                close_info = {"제목": "CLOSED", "일시": "-", "장소": "-", "성별": "-", "참가비": "-", "계좌": "-", "설명": "-", "연락처": "-", "마감일시": "-"}
                save_game_info(close_info)
                st.success("종료 완료"); st.rerun()

        with st.expander("기타 설정 (영상/건의/블랙리스트/비상수정)"):
            st.markdown("### 🎬 유튜브 영상 등록")
            with st.form("video_upload_admin"):
                v_title = st.text_input("영상 제목")
                v_url = st.text_input("유튜브 링크")
                if st.form_submit_button("영상 등록"):
                    if v_title and v_url: save_video_link(v_url, v_title); st.success("영상이 등록되었습니다.")
                    else: st.error("제목과 링크를 모두 입력하세요.")
            
            st.divider()
            st.markdown("### 🗣️ 건의사항 답변 관리")
            suggestions_data = load_suggestions()
            if suggestions_data: 
                df_sug = pd.DataFrame(suggestions_data)
                if '상태' not in df_sug.columns: df_sug['상태'] = '대기중'
                if '답변' not in df_sug.columns: df_sug['답변'] = ''

                edited_sug = st.data_editor(
                    df_sug, use_container_width=True,
                    column_config={"일시": st.column_config.TextColumn(disabled=True), "내용": st.column_config.TextColumn(disabled=True), "상태": st.column_config.SelectboxColumn("처리상태", options=["대기중", "완료", "보류"], required=True), "답변": st.column_config.TextColumn("관리자 답변", width="large")}, hide_index=True, num_rows="dynamic"
                )
                if st.button("💾 답변 저장하기", type="primary", key="save_sug_btn"):
                    update_suggestions(edited_sug); st.success("답변이 저장되었습니다!"); time.sleep(1); st.rerun()
            else: st.info("접수된 건의사항이 없습니다.")

            st.divider()
            st.markdown("### 🚨 블랙리스트 관리")
            with st.form("blacklist_admin"):
                b1, b2, b3 = st.columns(3)
                with b1: b_name = st.text_input("이름")
                with b2: b_phone = st.text_input("연락처")
                with b3: b_reason = st.text_input("사유")
                if st.form_submit_button("블랙리스트 추가"): add_to_blacklist(b_name, b_phone, b_reason); st.success("등록되었습니다.")

            st.divider()
            st.markdown("### 🛠️ 데이터 비상 수정 (Raw Editor)")
            if apps:
                edited_raw = st.data_editor(pd.DataFrame(apps), key="raw_edit")
                if st.button("비상 저장"): update_lineup(edited_raw); st.success("저장됨")
