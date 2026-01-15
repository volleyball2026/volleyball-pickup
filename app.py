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

# --- [설정] ---
DOC_NAME = "배구픽업관리"
SHEET_APPLICANTS = "참가자명단"
SHEET_GAME_INFO = "게임정보"
SHEET_HISTORY = "경기기록"
SHEET_BLACKLIST = "블랙리스트"
SHEET_MVP = "MVP투표"
SHEET_SUGGESTION = "건의함"
ADMIN_PASSWORD = "1992"

# --- [업데이트 로그] ---
UPDATE_LOGS = {
    "2026.01.15 (Ver 2.8)": [
        "🧹 [시스템] 중복 코드 제거 및 전체 최적화 (클린 버전)",
        "✨ [UI] 참가 신청 시 '시간(세트)' 선택 기능 추가",
        "🐛 [버그] 라인업 생성 시 참가자 누락 문제 완벽 해결"
    ],
    "2026.01.15 (Ver 2.7)": [
        "⚖️ [로직] 라인업 점수(일일) vs 뱃지 점수(영구) 분리",
        "🏆 [기능] 뱃지 시스템 & 명예의 전당 적용"
    ]
}

# --- [데이터 리스트] ---
POSITIONS_ALL = ["레프트", "속공", "세터", "라이트", "앞차", "백차", "레프트백", "센터백", "라이트백"]
POSITIONS_3RD = ["레프트백", "센터백", "라이트백", "속공"]
LEVELS = ["입문", "초급", "중급", "상급", "최상급"]
POSITION_QUOTAS = {"세터": 1, "레프트": 1, "라이트": 1, "속공": 1, "앞차": 1, "백차": 1, "레프트백": 1, "센터백": 1, "라이트백": 1}
LEVEL_MAP = {"입문": 1, "초급": 2, "중급": 3, "상급": 4, "최상급": 5}

# --- [뱃지 정의] ---
BADGE_DEFINITIONS = {
    "commander": {"icon": "🧠", "name": "코트의 사령관", "desc": "세터 5회 이상"},
    "thunder": {"icon": "🚀", "name": "천둥 스파이커", "desc": "공격수 10회 이상"},
    "all_rounder": {"icon": "🌈", "name": "올라운더", "desc": "5개 포지션 경험"},
    "celeb": {"icon": "⭐", "name": "인기스타", "desc": "MVP 10회 수상"},
    "scouter": {"icon": "🦅", "name": "독수리의 눈", "desc": "투표 10회 참여"},
    "rookie": {"icon": "🌱", "name": "슈퍼 루키", "desc": "5경기 내 MVP"},
    "guardian": {"icon": "👼", "name": "수호천사", "desc": "대기 3회 이상"},
    "iron_wall": {"icon": "🧱", "name": "통곡의 벽", "desc": "센터/센터백 5회"},
    "legend": {"icon": "🏅", "name": "터줏대감", "desc": "30회 참가 달성"},
    "levelup": {"icon": "🔥", "name": "성장왕", "desc": "레벨 상승 달성"}
}

# --- [세션 초기화] ---
if 'admin_logged_in' not in st.session_state: st.session_state['admin_logged_in'] = False
if 'lineup_admin_logged_in' not in st.session_state: st.session_state['lineup_admin_logged_in'] = False
if 'mvp_voter_verified' not in st.session_state: st.session_state['mvp_voter_verified'] = False
if 'mvp_voter_name' not in st.session_state: st.session_state['mvp_voter_name'] = ""
if 'mvp_voter_phone' not in st.session_state: st.session_state['mvp_voter_phone'] = ""

# --- [GSheet 연결] ---
@st.cache_resource
def get_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name(r"C:\Users\82106\service_account.json", scope)
        return gspread.authorize(creds)
    except: return None

def get_sheet_instance(sheet_name):
    client = get_connection()
    if client:
        try:
            doc = client.open(DOC_NAME)
            try: return doc.worksheet(sheet_name)
            except: return doc.add_worksheet(title=sheet_name, rows=100, cols=20)
        except: return None
    return None

# --- [유틸리티] ---
def normalize_phone(phone):
    if not phone: return ""
    phone = re.sub(r'\D', '', str(phone))
    if len(phone) == 11: return f"{phone[:3]}-{phone[3:7]}-{phone[7:]}"
    elif len(phone) == 10: return f"{phone[:3]}-{phone[3:6]}-{phone[6:]}"
    return phone

def anonymize_name(name):
    if not isinstance(name, str): return str(name)
    prefix = ""
    real_name = name
    if name.startswith("[VEGA]"):
        prefix = "[VEGA] "
        real_name = name.replace("[VEGA] ", "").strip()
    if len(real_name) <= 1: masked = real_name
    elif len(real_name) == 2: masked = real_name[0] + "O"
    else: masked = real_name[0] + "O" + real_name[2:]
    return prefix + masked

def simplify_level_name(level_full):
    return str(level_full).split(" ")[0]

# --- [핵심 기능 함수] ---
def save_game_info(info):
    sheet = get_sheet_instance(SHEET_GAME_INFO)
    if sheet:
        sheet.append_row(list(info.values()))
        st.cache_data.clear()

@st.cache_data(ttl=10)
def get_current_game_info():
    sheet = get_sheet_instance(SHEET_GAME_INFO)
    if sheet:
        all = sheet.get_all_records()
        if all: return all[-1]
    return None

def archive_current_game():
    src = get_sheet_instance(SHEET_APPLICANTS)
    dst = get_sheet_instance(SHEET_HISTORY)
    g_info = get_current_game_info()
    if src and dst and g_info:
        data = src.get_all_records()
        if not dst.get_all_values():
            dst.append_row(['일시', '게임제목', '이름', '연락처', '1순위', '레벨', '확정포지션'])
        if data:
            rows = []
            g_date = g_info.get('일시', datetime.now().strftime("%Y-%m-%d"))
            g_title = g_info.get('제목', 'Untitled')
            for p in data:
                rows.append([g_date, g_title, p.get('이름'), p.get('연락처'), p.get('1순위'), p.get('레벨'), p.get('확정1', '')])
            for r in rows: dst.append_row(r)
        st.cache_data.clear()

@st.cache_data(ttl=5)
def load_applicants():
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    return sheet.get_all_records() if sheet else []

def add_applicant(name, phone, level, pos1, pos2, pos3, note):
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        sheet.append_row([name, normalize_phone(phone), level, pos1, pos2, pos3, "", "", "", pos1, pos2, pos3, anonymize_name(name), "X", note])
        st.cache_data.clear()

def cancel_applicant(name, phone):
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        clean = normalize_phone(phone)
        try:
            cell_list = sheet.findall(name)
            for cell in cell_list:
                row_phone = sheet.cell(cell.row, 2).value
                if normalize_phone(row_phone) == clean:
                    sheet.delete_rows(cell.row)
                    st.cache_data.clear()
                    return True, "취소되었습니다."
            return False, "정보가 일치하지 않습니다."
        except: return False, "오류 발생"

def update_lineup(df):
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        sheet.clear()
        headers = ["이름", "연락처", "레벨", "1순위", "2순위", "3순위", "팀1", "팀2", "팀3", "확정1", "확정2", "확정3", "이름(가림)", "입금", "비고"]
        sheet.append_row(headers)
        if '이름(가림)' not in df.columns: df['이름(가림)'] = df['이름'].apply(anonymize_name)
        if '입금' not in df.columns: df['입금'] = 'X'
        if '비고' not in df.columns: df['비고'] = ''
        sheet.append_rows(df[headers].values.tolist())
        st.cache_data.clear()

def clear_applicants():
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        sheet.clear()
        sheet.append_row(["이름", "연락처", "레벨", "1순위", "2순위", "3순위", "팀1", "팀2", "팀3", "확정1", "확정2", "확정3", "이름(가림)", "입금", "비고"])
        st.cache_data.clear()

def check_blacklist(name, phone):
    sheet = get_sheet_instance(SHEET_BLACKLIST)
    if sheet:
        clean = normalize_phone(phone)
        for r in sheet.get_all_records():
            if r['이름'] == name and normalize_phone(r['연락처']) == clean: return True, r['사유']
    return False, ""

def add_to_blacklist(name, phone, reason):
    sheet = get_sheet_instance(SHEET_BLACKLIST)
    if sheet: sheet.append_row([name, normalize_phone(phone), reason, datetime.now().strftime("%Y-%m-%d")])

# [기록 조회 함수들]
@st.cache_data(ttl=60)
def get_my_history(name, phone):
    sheet = get_sheet_instance(SHEET_HISTORY)
    history = []
    if sheet:
        clean = normalize_phone(phone)
        try:
            for r in sheet.get_all_records():
                if r.get('이름') == name and normalize_phone(r.get('연락처')) == clean: history.append(r)
        except: pass
    return history

@st.cache_data(ttl=60)
def load_all_history():
    sheet = get_sheet_instance(SHEET_HISTORY)
    return sheet.get_all_records() if sheet else []

@st.cache_data(ttl=60)
def load_all_mvp_records():
    sheet = get_sheet_instance(SHEET_MVP)
    return sheet.get_all_records() if sheet else []

# [MVP 관련]
def save_mvp_vote(voter, phone, candidate):
    sheet = get_sheet_instance(SHEET_MVP)
    if sheet:
        clean = normalize_phone(phone)
        today = datetime.now().strftime("%Y-%m-%d")
        for r in sheet.get_all_records():
            if r['투표자이름'] == voter and normalize_phone(r['투표자연락처']) == clean and r['일시'] == today:
                return False, "이미 투표하셨습니다."
        sheet.append_row([today, voter, clean, candidate])
        st.cache_data.clear()
        return True, "투표 완료!"
    return False, "오류"

@st.cache_data(ttl=10)
def get_mvp_ranking_today():
    sheet = get_sheet_instance(SHEET_MVP)
    if sheet:
        data = sheet.get_all_records()
        if not data: return pd.DataFrame()
        today = datetime.now().strftime("%Y-%m-%d")
        votes = [r['MVP후보'] for r in data if r.get('일시') == today]
        if not votes: return pd.DataFrame()
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
        if not data: return []
        df = pd.DataFrame(data)
        if '일시' not in df.columns or 'MVP후보' not in df.columns: return []
        daily = df.groupby(['일시', 'MVP후보']).size().reset_index(name='득표수')
        idx = daily.groupby(['일시'])['득표수'].transform(max) == daily['득표수']
        return daily[idx].sort_values('일시', ascending=False)
    return []

@st.cache_data(ttl=60)
def get_my_mvp_stats(name, phone):
    sheet = get_sheet_instance(SHEET_MVP)
    received, voted = 0, 0
    if sheet:
        clean = normalize_phone(phone)
        for r in sheet.get_all_records():
            if r.get('MVP후보') == name: received += 1
            if r.get('투표자이름') == name and normalize_phone(r.get('투표자연락처')) == clean: voted += 1
    return received, voted

# [건의함]
def save_suggestion(message):
    sheet = get_sheet_instance(SHEET_SUGGESTION)
    if sheet:
        sheet.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message])
        return True
    return False

def load_suggestions():
    sheet = get_sheet_instance(SHEET_SUGGESTION)
    return sheet.get_all_records() if sheet else []

# [뱃지 계산 로직]
def calculate_badges(name, phone, all_hist, all_mvp, current_level_str=""):
    badges = []
    clean_phone = normalize_phone(phone)
    my_hist = [h for h in all_hist if h.get('이름') == name and normalize_phone(h.get('연락처')) == clean_phone]
    
    my_mvp_received = len([m for m in all_mvp if m.get('MVP후보') == name])
    my_mvp_voted = len([m for m in all_mvp if m.get('투표자이름') == name and normalize_phone(m.get('투표자연락처')) == clean_phone])
    
    setter_cnt = len([h for h in my_hist if '세터' in str(h.get('1순위', ''))])
    if setter_cnt >= 5: badges.append("commander")
    
    attacker_cnt = len([h for h in my_hist if any(x in str(h.get('1순위', '')) for x in ['레프트', '라이트', '속공'])])
    if attacker_cnt >= 10: badges.append("thunder")
    
    pos_types = set([str(h.get('1순위', '')).strip() for h in my_hist if h.get('1순위')])
    if len(pos_types) >= 5: badges.append("all_rounder")
    
    if my_mvp_received >= 10: badges.append("celeb")
    if my_mvp_voted >= 10: badges.append("scouter")
    if 0 < len(my_hist) <= 5 and my_mvp_received >= 1: badges.append("rookie")
    
    wait_cnt = len([h for h in my_hist if str(h.get('확정포지션', '')).strip() == '대기'])
    if wait_cnt >= 3: badges.append("guardian")
    
    center_cnt = len([h for h in my_hist if any(x in str(h.get('1순위', '')) for x in ['센터백', '속공'])])
    if center_cnt >= 5: badges.append("iron_wall")
    
    if len(my_hist) >= 30: badges.append("legend")
    
    if my_hist and current_level_str:
        first = LEVEL_MAP.get(my_hist[0].get('레벨', '입문').split(" ")[0], 1)
        curr = LEVEL_MAP.get(current_level_str.split(" ")[0], 1)
        if curr > first: badges.append("levelup")
        
    return badges

# [차트 그리기]
def draw_radar_chart(stats):
    cats = ['🔥참여율', '✨매너', '❤️헌신', '🌈다양성', '🤝사교성']
    vals = [stats['participation'], stats['manner'], stats['dedication'], stats['diversity'], stats['social']]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=vals, theta=cats, fill='toself', name='Stats',
        line=dict(color='#FF5722'), fillcolor='rgba(255, 87, 34, 0.4)'
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100], showticklabels=False)),
        showlegend=False, margin=dict(l=40, r=40, t=30, b=30), height=300,
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
    )
    return fig

# [공유 텍스트]
def generate_kakao_text(df):
    text = "🏐 [이번 주 배구 픽업 라인업] 🏐\n\n"
    for i, (ct, cp) in enumerate([("팀1","확정1"), ("팀2","확정2"), ("팀3","확정3")], 1):
        if cp not in df.columns: continue
        text += f"==== {i*2-1}·{i*2}세트 ====\n"
        playing = df[df[cp] != '']
        if playing.empty: text += "(미정)\n\n"; continue
        text += "🔴 A팀\n"
        for _, r in playing[(playing[ct]=="A팀") & (playing[cp]!="대기")].iterrows(): text += f"- {r[cp]}: {r['이름']}\n"
        text += "\n🔵 B팀\n"
        for _, r in playing[(playing[ct]=="B팀") & (playing[cp]!="대기")].iterrows(): text += f"- {r[cp]}: {r['이름']}\n"
        text += "\n🛌 대기\n"
        bench = playing[playing[cp]=="대기"]
        if bench.empty: text += "-\n"
        else:
            for _, r in bench.iterrows(): text += f"- {r['이름']}\n"
        text += "\n"
    return text

# --- [알고리즘: 일일 점수 누적 + 세트 필터링] ---
def get_priority_score_daily(player, daily_history, daily_hardship):
    name = player['이름']
    score = 50.0 
    reasons = ["기본(50)"]
    
    if "[VEGA]" in name: score += 100.0; reasons.append("+VEGA(100)")
    
    # 일일 배정 누적 (패널티)
    today_assign = daily_history.get(name, 0)
    if today_assign > 0:
        penalty = today_assign * 10.0
        score -= penalty
        reasons.append(f"-배정{today_assign}회({int(penalty)})")
    
    # 일일 기여도 (마일리지)
    today_hardship = daily_hardship.get(name, 0)
    if today_hardship > 0:
        score += today_hardship
        reasons.append(f"+기여{int(today_hardship)}")
        
    score += random.random()
    return score, " ".join(reasons)

def assign_team(team_members):
    team_members.sort(key=lambda x: x['priority_score'], reverse=True)
    for p in team_members: p['assigned_pos'] = None; p['match_type'] = 'random'
    
    team_size = len(team_members)
    quotas = POSITION_QUOTAS.copy()
    
    if team_size == 8:
        c_fast = sum(1 for p in team_members if '속공' in [str(p['1순위']), str(p['2순위'])])
        c_cb = sum(1 for p in team_members if '센터백' in [str(p['1순위']), str(p['2순위'])])
        if c_fast >= c_cb: quotas['센터백'] = 0
        else: quotas['속공'] = 0
    elif team_size == 7: quotas['속공'] = 0; quotas['센터백'] = 0
    elif team_size == 6: quotas['속공'] = 0; quotas['센터백'] = 0; quotas['백차'] = 0
    
    for step in [1, 2, 3]:
        for p in team_members:
            if p['assigned_pos']: continue
            wish = str(p.get(f'{step}순위', '')).strip()
            if wish and wish != "선택 안함" and quotas.get(wish, 0) > 0:
                p['assigned_pos'] = wish
                quotas[wish] -= 1
                if step == 1: p['match_type'] = '1st'
                elif step == 2: p['match_type'] = '2nd'
                elif step == 3: p['match_type'] = '3rd'
    
    for p in team_members:
        if not p['assigned_pos']:
            filled = False
            for pos, q in quotas.items():
                if q > 0:
                    p['assigned_pos'] = pos; quotas[pos] -= 1
                    p['match_type'] = 'random'; filled = True; break
            if not filled: p['assigned_pos'] = "대기"; p['match_type'] = 'wait'
    return team_members

def generate_vega_priority_schedule(df):
    base_pool = df.to_dict('records')
    # 일일 누적 초기화 (0점 시작)
    daily_history = {p['이름']: 0 for p in base_pool}
    daily_hardship = {p['이름']: 0 for p in base_pool}
    final_rounds = {}

    for round_num in range(1, 4):
        # [세트 필터링]
        target_set = f"{round_num*2-1}·{round_num*2}"
        valid_markers = ["1·2", "3·4", "5·6"]
        
        current_pool = []
        for p in base_pool:
            note = str(p.get('비고', ''))
            has_marker = any(m in note for m in valid_markers)
            if has_marker:
                if target_set in note: current_pool.append(p.copy())
            else:
                current_pool.append(p.copy())

        # 점수 계산 (이번 라운드 참가자만)
        for p in current_pool:
            sc, re = get_priority_score_daily(p, daily_history, daily_hardship)
            p['priority_score'] = sc; p['score_reason'] = re
            
        current_pool.sort(key=lambda x: x['priority_score'], reverse=True)
        
        # 팀 분배
        match_cap = len(current_pool)
        vegas = [p for p in current_pool if "[VEGA]" in p['이름']]
        pickups = [p for p in current_pool if "[VEGA]" not in p['이름']]
        
        size_a = (match_cap + 1) // 2
        team_a = []; team_b = []
        
        for v in vegas:
            if len(team_a) < size_a: team_a.append(v)
            else: team_b.append(v)
        for pk in pickups:
            if len(team_a) < size_a: team_a.append(pk)
            else: team_b.append(pk)
            
        final_a = assign_team(team_a)
        final_b = assign_team(team_b)
        
        # [상태 업데이트] 다음 라운드를 위한 누적
        for p in final_a + final_b:
            nm = p['이름']; mt = p.get('match_type')
            # 1순위 배정 시 패널티 증가
            if mt == '1st': daily_history[nm] += 1
            # 기여 시 보너스 증가
            if mt == 'wait': daily_hardship[nm] += 10
            elif mt == '3rd': daily_hardship[nm] += 5
            elif mt in ['2nd', 'random']: daily_hardship[nm] += 3
            
        final_rounds[round_num] = (final_a, final_b)
        
    return final_rounds

# --- [메인 화면] ---
st.set_page_config(page_title="여순광 배구 픽업", page_icon="🏐", layout="wide") 
st.markdown("<style>div[data-testid='stTabsNav']{position:sticky;top:0;z-index:999;background:white;padding-top:1rem;}</style>", unsafe_allow_html=True)

with st.sidebar:
    st.header("📢 Update Log")
    for d, logs in UPDATE_LOGS.items():
        with st.expander(d):
            st.markdown("".join([f"- {l}\n" for l in logs]))
    st.divider()
    st.markdown("### 📞 문의하기\n[오픈채팅방 입장](https://open.kakao.com/o/gf1s6t9h)")
    if get_sheet_instance(SHEET_APPLICANTS): st.success("✅ 서버 연결됨")
    else: st.error("❌ 서버 연결 실패")

st.title("🏐 여순광 배구 픽업게임 매니저")
current_game = get_current_game_info()

tab0, tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🔰 운영 안내", "📢 참가 신청", "📋 라인업 공개", "📊 My Page", "🏆 MVP", "🗣️ 소리함", "⚡ 라인업 생성(관리자)", "⚙️ 관리자"
])

# --- 탭 0: 운영 안내 ---
with tab0:
    st.info("📢 **[중요] 1~2월 시범 운영 안내**")
    st.markdown("매주 목요일 18:30~21:30 순천조례초 체육관 / VEGA팀 협력 운영")

# --- 탭 1: 참가 신청 ---
with tab1:
    if 'reg_success' not in st.session_state: st.session_state['reg_success'] = False
    if 'reg_name' not in st.session_state: st.session_state['reg_name'] = ""
    if 'reg_is_late' not in st.session_state: st.session_state['reg_is_late'] = False

    if current_game:
        deadline_str = str(current_game.get('마감일시', '2099-12-31 23:59'))
        try: deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
        except: deadline_dt = datetime(2099, 12, 31, 23, 59)
        now = datetime.utcnow() + timedelta(hours=9)
        is_expired = now > deadline_dt

        st.subheader(f"[{current_game['성별']}] {current_game['제목']}")
        c1, c2 = st.columns(2)
        with c1: st.write(f"**📅 일시:** {current_game['일시']}"); st.write(f"**📍 장소:** {current_game['장소']}")
        with c2: 
            st.write(f"**💰 참가비:** {current_game['참가비']}")
            if is_expired: st.error(f"**⏰ 마감:** {deadline_str} (종료)")
            else: st.info(f"**⏰ 마감:** {deadline_str} 까지")
        st.divider()

        if st.session_state['reg_success']:
            msg_name = st.session_state['reg_name']
            if st.session_state['reg_is_late']:
                st.success(f"✅ {msg_name}님, **대기(추가) 명단**에 등록되었습니다!")
                st.markdown("""📢 **잠깐! 아직 확정이 아닙니다.**\n마감 후 신청이므로, 아래 버튼을 눌러 운영진에게 **승인 요청**을 해주세요.""")
                st.link_button("💬 운영진에게 승인 요청하기 (오픈채팅)", "https://open.kakao.com/o/gf1s6t9h", use_container_width=True)
            else: st.success(f"✅ {msg_name}님 신청 완료!"); 
            if st.button("확인 (메시지 닫기)"): st.session_state['reg_success'] = False; st.rerun()
            st.divider()

        if is_expired: st.warning("⚠️ **정규 신청이 마감되었습니다.** 현재는 **'대기/추가'** 등록만 가능합니다.")
        
        st.write("### 👇 참가 신청서")
        with st.form("apply_form"):
            c1, c2 = st.columns(2)
            with c1: name = st.text_input("이름")
            with c2: phone = st.text_input("연락처", placeholder="01012345678")
            
            with st.expander("ℹ️ 레벨 기준 보기 (클릭)", expanded=False):
                st.markdown("- **입문**: 기본기 부족\n- **초급**: 경험 적음\n- **중급**: 전국대회 가능\n- **상급**: 전국대회 상위\n- **최상급**: 선출 준함")
            is_vega = st.checkbox("순천VEGA 회원 (우선권)")
            
            # [시간 선택 기능]
            st.markdown("---")
            st.write("**⏱️ 참가 가능 시간(세트) 선택**")
            set_options = ["1·2세트 (19:20 ~ 20:00)", "3·4세트 (20:00 ~ 20:40)", "5·6세트 (20:40 ~ 21:20)"]
            selected_sets = st.multiselect("참가할 세트를 모두 선택해주세요", options=set_options, default=set_options)
            
            lc1, lc2 = st.columns(2)
            with lc1: level = st.selectbox("참가자 레벨", LEVELS)
            # note는 자동 생성
            
            st.markdown("---")
            if not is_expired: st.info("📢 **주의:** 1순위 포지션 경쟁이 치열할 경우(7명 이상), **점수 및 밸런스**에 따라 2·3순위로 밀리거나 임의 배정될 수 있습니다.")
            p1, p2, p3 = st.columns(3)
            with p1: pos1 = st.selectbox("1순위 (필수)", POSITIONS_ALL)
            with p2: pos2 = st.selectbox("2순위 (선택)", ["선택 안함"] + POSITIONS_ALL)
            with p3: pos3 = st.selectbox("3순위 (수비/속공)", ["선택 안함"] + POSITIONS_3RD)
            
            submit_label = "대기/추가 등록하기 (마감됨)" if is_expired else "신청하기"
            
            if st.form_submit_button(submit_label):
                if name and phone:
                    if not selected_sets: st.error("❌ 최소 1개 이상의 세트를 선택해야 합니다.")
                    else:
                        is_black, reason = check_blacklist(name, phone)
                        if is_black: st.error(f"🚨 신청 불가: {reason}")
                        else:
                            final_name = f"[VEGA] {name}" if is_vega else name
                            # 세트 정보 저장
                            sets_str = ", ".join([s.split("세트")[0] for s in selected_sets])
                            try:
                                add_applicant(final_name, phone, level, pos1, "" if pos2=="선택 안함" else pos2, "" if pos3=="선택 안함" else pos3, sets_str)
                                st.session_state['reg_success'] = True; st.session_state['reg_name'] = name; st.session_state['reg_is_late'] = is_expired
                                st.toast(f"✅ {name}님 등록이 완료되었습니다!", icon="🎉"); st.rerun()
                            except Exception as e: st.error(f"❌ 저장 중 오류: {str(e)}")
                else: st.error("필수 입력 누락"); st.toast("⚠️ 이름과 연락처를 입력해주세요!", icon="🚨")
        
        with st.expander("🗑️ 신청 취소"):
            with st.form("cancel"):
                cc1, cc2 = st.columns(2)
                with cc1: c_name = st.text_input("이름")
                with cc2: c_phone = st.text_input("연락처")
                if st.form_submit_button("취소하기"):
                    # 마감 후 알림
                    if is_expired: save_suggestion(f"🚨 [마감후취소] {c_name} ({c_phone}) 취소")
                    
                    suc, msg = cancel_applicant(c_name, c_phone)
                    if not suc: suc, msg = cancel_applicant(f"[VEGA] {c_name}", c_phone)
                    if suc: st.success(msg); st.toast("🗑️ 취소되었습니다."); st.rerun() 
                    else: st.error(msg)

        st.divider()
        st.subheader("📊 신청 현황")
        applicants = load_applicants()
        if applicants:
            df_public = pd.DataFrame(applicants)
            st.markdown("##### 🚦 포지션 경쟁률 (정원: 6명)")
            if '1순위' in df_public.columns:
                pos_counts = df_public['1순위'].value_counts()
                html_code = """<style>.pos-container {display: grid; grid-template-columns: repeat(auto-fit, minmax(80px, 1fr)); gap: 8px; margin-bottom: 20px;}.pos-card {background-color: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 8px 4px; text-align: center; box-shadow: 0 1px 2px rgba(0,0,0,0.05);}.pos-title {font-size: 0.85em; color: #666; margin-bottom: 4px; font-weight: bold;}.pos-count {font-size: 1.4em; font-weight: 900; line-height: 1.2; margin-bottom: 2px;}.pos-status {font-size: 0.75em; font-weight: bold;}.status-safe {color: #2E7D32; background-color: #E8F5E9; border-radius: 4px; padding: 2px 4px; display:inline-block;} .status-warn {color: #E65100; background-color: #FFF3E0; border-radius: 4px; padding: 2px 4px; display:inline-block;} .status-max {color: #1565C0; background-color: #E3F2FD; border-radius: 4px; padding: 2px 4px; display:inline-block;} .status-full {color: #C62828; background-color: #FFEBEE; border-radius: 4px; padding: 2px 4px; display:inline-block;} </style><div class="pos-container">"""
                for pos in POSITIONS_ALL:
                    count = pos_counts.get(pos, 0)
                    if count >= 7: status_class, status_text = "status-full", "초과"
                    elif count == 6: status_class, status_text = "status-max", "마감"
                    elif count == 5: status_class, status_text = "status-warn", "임박"
                    else: status_class, status_text = "status-safe", "여유"
                    html_code += f"""<div class="pos-card"><div class="pos-title">{pos}</div><div class="pos-count" style="color:#333;">{count}<span style="font-size:0.5em; font-weight:normal; color:#888;">명</span></div><div class="pos-status"><span class="{status_class}">{status_text}</span></div></div>"""
                html_code += "</div>"
                st.markdown(html_code, unsafe_allow_html=True)
            
            st.divider()
            col_list, col_stats = st.columns([2.2, 1])
            with col_list:
                st.markdown("##### 📋 신청자 명단")
                if '입금' not in df_public.columns: df_public['입금'] = "X"
                df_public['상태'] = df_public['입금'].apply(lambda x: "✅ 확인" if str(x).strip().upper() == "O" else "-")
                if '이름' in df_public.columns: df_public['이름'] = df_public['이름'].apply(anonymize_name)
                if '레벨' in df_public.columns: df_public['레벨'] = df_public['레벨'].apply(simplify_level_name) 
                if '비고' not in df_public.columns: df_public['비고'] = ""
                show_cols = ["이름", "상태", "레벨", "1순위", "비고"]
                real_cols = [c for c in show_cols if c in df_public.columns]
                st.dataframe(df_public[real_cols], hide_index=True, use_container_width=True, height=500)

            with col_stats:
                st.markdown("##### 🍰 레벨 분포")
                if '레벨' in df_public.columns:
                    level_counts = df_public['레벨'].value_counts()
                    chart_data = []
                    for lv in LEVELS: 
                        cnt = level_counts.get(lv, 0)
                        legend_label = f"{lv} ({cnt}명)"
                        chart_text = f"{lv} {cnt}명" if cnt > 0 else ""
                        chart_data.append({"Level": lv, "Count": cnt, "LegendLabel": legend_label, "ChartText": chart_text})
                    df_chart = pd.DataFrame(chart_data)
                    base = alt.Chart(df_chart).encode(theta=alt.Theta("Count", stack=True))
                    pie = base.mark_arc(outerRadius=80, innerRadius=40).encode(color=alt.Color("LegendLabel", title="레벨 현황", sort=None), tooltip=["Level", "Count"])
                    text = base.mark_text(radius=60).encode(text=alt.Text("ChartText"), order=alt.Order("Level"), color=alt.value("black"))
                    st.altair_chart(pie + text, use_container_width=True)

                st.markdown("##### 📌 요약 정보")
                with st.container(border=True):
                    total_cnt = len(df_public)
                    vega_cnt = len([n for n in df_public['이름'] if "[VEGA]" in str(n)])
                    pickup_cnt = total_cnt - vega_cnt
                    if not is_expired:
                        diff = deadline_dt - now
                        hours = diff.seconds // 3600 + (diff.days * 24)
                        mins = (diff.seconds % 3600) // 60
                        time_msg = f"{hours}시간 {mins}분 전"
                        time_color = "blue"
                    else: time_msg = "마감됨"; time_color = "red"
                    st.markdown(f"""- **총 인원**: **{total_cnt}명**\n- <span style='color:green'>VEGA {vega_cnt}명</span> / <span style='color:blue'>픽업 {pickup_cnt}명</span>\n- **마감까지**: <span style='color:{time_color}; font-weight:bold;'>{time_msg}</span>""", unsafe_allow_html=True)
        else: st.info("아직 신청자가 없습니다.")
    else: st.warning("모집 중인 게임이 없습니다.")

# --- 탭 2: 라인업 공개 ---
with tab2:
    with st.expander("📘 이용 가이드: 배정 기준 및 보는 법", expanded=False):
        st.markdown("""
        **1. 배정 기준 (우선순위 점수제)**
        | 항목 | 점수 | 설명 |
        | :--- | :--- | :--- |
        | **기본 점수** | `50점` | 모든 참가자 기본 지급 |
        | **VEGA 회원** | `+100점` | **우선권 부여** |
        | **1순위 배정** | `-10점`/회 | 오늘 1순위를 많이 할수록 **배정 누적**되어 양보 유도 |
        | **기여도** | `+3~10점` | 대기/비선호 수행 시 점수 적립 |

        **2. 화면 보는 법**
        - **팀 확인**: A팀(🔴) / B팀(🔵)
        - **아이콘**: 
            - <span style='color:#1565C0; background-color:#E3F2FD; padding:1px 4px; border-radius:4px; font-weight:bold; font-size:0.8em;'>1순위</span> : 1순위 희망 포지션 배정
            - <span style='color:#2E7D32; background-color:#E8F5E9; padding:1px 4px; border-radius:4px; font-weight:bold; font-size:0.8em;'>2순위</span> : 2순위 희망 포지션 배정
            - <span style='color:#E65100; background-color:#FFF3E0; padding:1px 4px; border-radius:4px; font-weight:bold; font-size:0.8em;'>3순위</span> : 3순위 희망 포지션 배정
            - <span style='color:#C62828; background-color:#FFEBEE; padding:1px 4px; border-radius:4px; font-weight:bold; font-size:0.8em;'>무</span> : 무작위(임의) 배정
        """, unsafe_allow_html=True)

    st.header("📋 이번 주 라인업")
    data_final = load_applicants()
    if not data_final: st.info("확정 전")
    else:
        df_final = pd.DataFrame(data_final)
        df_final = df_final.drop_duplicates(subset=['이름', '연락처'], keep='last')
        df_final['이름_masked'] = df_final['이름'].apply(anonymize_name)
        
        st.divider()
        lineup_tabs = st.tabs(["1·2 세트", "3·4 세트", "5·6 세트"])
        for i, (col_team, col_pos) in enumerate([("팀1", "확정1"), ("팀2", "확정2"), ("팀3", "확정3")], 1):
            with lineup_tabs[i-1]:
                if col_pos in df_final.columns:
                    playing = df_final[df_final[col_pos].astype(str).str.strip() != '']
                    if not playing.empty:
                        real_players = playing[playing[col_pos] != "대기"]
                        if not real_players.empty:
                            team_a_df = real_players[real_players[col_team]=="A팀"]; team_b_df = real_players[real_players[col_team]=="B팀"]
                            count_a = len(team_a_df); count_b = len(team_b_df)
                            
                            def get_missing_pos(df_team, pos_col):
                                if df_team.empty: return []
                                current_pos = set(df_team[pos_col].unique())
                                full_set = set(POSITIONS_ALL) 
                                missing = list(full_set - current_pos)
                                sort_order = {p: idx for idx, p in enumerate(POSITIONS_ALL)}
                                missing.sort(key=lambda x: sort_order.get(x, 99))
                                return missing

                            missing_a = get_missing_pos(team_a_df, col_pos); missing_b = get_missing_pos(team_b_df, col_pos)
                            info_msg = f"📢 **[{i*2-1}·{i*2}세트] {count_a} vs {count_b} 경기**"
                            if count_a != count_b: info_msg += f" (🔴A제외: {', '.join(missing_a) if missing_a else '없음'} | 🔵B제외: {', '.join(missing_b) if missing_b else '없음'})"
                            st.info(info_msg)

                        def get_badge(row, pos_col):
                            current = str(row[pos_col]).strip(); w1 = str(row.get('1순위', '')).strip()
                            if current == w1: return "<span style='color:#1565C0; background-color:#E3F2FD; padding:2px 6px; border-radius:4px; font-weight:bold; border:1px solid #1565C0;'>1순위</span>"
                            return "<span style='color:#C62828; background-color:#FFEBEE; padding:2px 6px; border-radius:4px; font-weight:bold; border:1px solid #C62828;'>무</span>"

                        c1, c2 = st.columns(2)
                        with c1:
                            st.error(f"🔴 A팀 (VEGA)")
                            for _, r in playing[(playing[col_team]=="A팀") & (playing[col_pos]!="대기")].iterrows():
                                st.markdown(f"- **{r[col_pos]}**: {r['이름_masked']} {get_badge(r, col_pos)}", unsafe_allow_html=True)
                        with c2:
                            st.info(f"🔵 B팀 (픽업)")
                            for _, r in playing[(playing[col_team]=="B팀") & (playing[col_pos]!="대기")].iterrows():
                                st.markdown(f"- **{r[col_pos]}**: {r['이름_masked']} {get_badge(r, col_pos)}", unsafe_allow_html=True)
                        st.markdown("---")
                        bench = playing[playing[col_pos]=="대기"]
                        if not bench.empty:
                            st.caption(f"🛌 **대기**")
                            for _, r in bench.iterrows(): st.write(f"- {r['이름_masked']} (희망: {r.get('1순위','')})")
                else: st.warning("배정 정보 없음")

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
            st.session_state['my_name'] = input_name; st.session_state['my_phone'] = input_phone
            st.toast(f"{input_name}님 기록을 조회합니다.", icon="🔍")

    if st.session_state['my_name'] and st.session_state['my_phone']:
        my_name = st.session_state['my_name']
        my_phone = st.session_state['my_phone']
        clean_phone = normalize_phone(my_phone)
        
        hist = get_my_history(my_name, my_phone)
        mvp_received, mvp_voted = get_my_mvp_stats(my_name, my_phone)
        cur_apps = load_applicants()
        my_cur = [p for p in cur_apps if (p['이름']==my_name or p['이름']==f"[VEGA] {my_name}") and normalize_phone(p['연락처'])==clean_phone]
        
        # 실시간 스탯 반영 (Preview)
        if my_cur:
            p_cur = my_cur[0]
            # 확정 포지션이 있으면 통계에 임시 추가
            for r in range(1, 4):
                if str(p_cur.get(f'확정{r}', '')).strip():
                    hist.append({'이름':my_name, '1순위':p_cur.get('1순위'), '확정포지션':p_cur.get(f'확정{r}'), '레벨':p_cur.get('레벨')})
                    break # 하나만 추가 (단순화)

        score_part = min(len(hist) * 5, 100)
        score_manner = min(mvp_received * 10, 100)
        unique_pos = set([str(h.get('1순위', '')).strip() for h in hist if h.get('1순위')])
        score_div = min(len(unique_pos) * 15, 100)
        score_social = min(mvp_voted * 5, 100)
        dedication_count = sum([2 if h.get('확정포지션')=='대기' else (1 if str(h.get('확정포지션'))!=str(h.get('1순위')) else 0) for h in hist])
        score_dedic = min(dedication_count * 15, 100) 
        stats = {'participation': score_part, 'manner': score_manner, 'dedication': score_dedic, 'diversity': score_div, 'social': score_social}

        # 뱃지 계산
        all_hist = load_all_history()
        all_mvp = load_all_mvp_records()
        my_badges = calculate_badges(my_name, clean_phone, all_hist, all_mvp, my_cur[0].get('레벨','') if my_cur else "")

        st.divider()
        st.subheader("🏆 나의 트로피 진열장")
        if my_badges:
            b_cols = st.columns(5)
            for i, b_code in enumerate(my_badges):
                b_info = BADGE_DEFINITIONS.get(b_code, {})
                with b_cols[i % 5]:
                    st.markdown(f"<div style='text-align:center; border:1px solid #eee; border-radius:10px; padding:5px;'><h1>{b_info.get('icon','')}</h1><small>{b_info.get('name','')}</small></div>", unsafe_allow_html=True)
        else: st.info("획득한 뱃지가 없습니다.")
        
        st.divider()
        col_chart, col_info = st.columns([1.2, 1])
        with col_chart:
            try: st.plotly_chart(draw_radar_chart(stats), use_container_width=True, config={'staticPlot': True})
            except: st.error("차트 오류")
        with col_info:
            st.markdown("#### 📌 요약")
            st.write(f"- 총 참여: {len(hist)}회 / MVP: {mvp_received}회 / 헌신: {dedication_count}p")
            if my_cur:
                p = my_cur[0]
                status_list = []
                for i in range(1, 4):
                    if p.get(f'확정{i}'): status_list.append(f"- {i*2-1}·{i*2}세트: {p.get(f'팀{i}')} {p.get(f'확정{i}')}")
                if status_list: 
                    for s in status_list: st.write(s)
                else: st.success("신청 완료") if p.get('입금')=='O' else st.warning("대기 중")

# --- 탭 4: MVP ---
with tab4:
    with st.expander("📘 이용 가이드: MVP 투표", expanded=False):
        st.write("🔒 개인정보 보호를 위해 참가자 본인 인증 후 투표 및 결과 확인이 가능합니다.")

    st.header("🏆 MVP 투표")
    apps = load_applicants()
    if not apps: st.warning("참가자 명단이 없어 투표할 수 없습니다.")
    else:
        auth_placeholder = st.empty()
        if not st.session_state['mvp_voter_verified']:
            with auth_placeholder.form("mvp_auth"):
                st.info("🔒 투표 및 결과 확인을 위해 본인 인증이 필요합니다.")
                voter = st.text_input("이름"); vphone = st.text_input("연락처")
                if st.form_submit_button("확인"):
                    clean_vphone = normalize_phone(vphone); found = False
                    for p in apps:
                        p_name_real = p['이름'].replace("[VEGA] ", "")
                        if p_name_real == voter and normalize_phone(p['연락처']) == clean_vphone: found = True; break
                    if found: st.session_state['mvp_voter_verified'] = True; st.session_state['mvp_voter_name'] = voter; st.session_state['mvp_voter_phone'] = clean_vphone; auth_placeholder.empty()
                    else: st.error("참가자 명단에 없는 정보입니다.")
        
        if st.session_state['mvp_voter_verified']:
            st.success(f"👋 환영합니다, {st.session_state['mvp_voter_name']}님!")
            with st.form("mvp_submit"):
                target_name = st.selectbox("🏅 MVP 선택", [p['이름'] for p in apps])
                if st.form_submit_button("투표하기"):
                    suc, msg = save_mvp_vote(st.session_state['mvp_voter_name'], st.session_state['mvp_voter_phone'], target_name)
                    if suc: st.success(msg)
                    else: st.error(msg)
            if st.button("로그아웃"): st.session_state['mvp_voter_verified'] = False; st.rerun()
            st.divider(); st.subheader("📊 득표 현황"); st.dataframe(get_mvp_ranking_today(), use_container_width=True)
            st.markdown("---"); st.subheader("👑 명예의 전당"); st.dataframe(get_mvp_hall_of_fame(), use_container_width=True)

# --- 탭 5: 소리함 ---
with tab5:
    st.header("🗣️ 소리함 (익명)")
    with st.form("suggestion_box"):
        msg = st.text_area("내용", height=150)
        if st.form_submit_button("보내기"):
            if msg:
                if save_suggestion(msg): st.success("전송 완료!")
                else: st.error("전송 실패")
            else: st.warning("내용을 입력해주세요.")

# --- 탭 6: 라인업 생성 (관리자) ---
with tab6:
    st.header("⚡ 공정 라인업 생성")
    lineup_auth = st.empty()
    if not st.session_state['lineup_admin_logged_in']:
        with lineup_auth.form("lineup_login"):
            pw2 = st.text_input("비밀번호", type="password")
            if st.form_submit_button("확인"):
                if pw2 == ADMIN_PASSWORD: st.session_state['lineup_admin_logged_in'] = True; lineup_auth.empty()
                else: st.error("비밀번호 불일치")
    
    if st.session_state['lineup_admin_logged_in']:
        data = load_applicants()
        if not data: st.warning("참가자 없음")
        else:
            df = pd.DataFrame(data)
            with st.expander("💬 카카오톡 공유 텍스트"): st.code(generate_kakao_text(df), language="text")
            st.divider()

            # [복구 로직] 저장된 데이터가 있으면 점수 상태 재계산 (Replay)
            if 'fair_results' not in st.session_state and '확정1' in df.columns:
                if df['확정1'].astype(str).str.strip().any():
                    d_hist = {p['이름']: 0 for p in data}
                    d_hard = {p['이름']: 0 for p in data}
                    res = {}
                    for r in range(1, 4):
                        cp = f"확정{r}"; ct = f"팀{r}"
                        ta = []; tb = []
                        # 점수 계산
                        for p in data:
                            sc, re = get_priority_score_daily(p, d_hist, d_hard)
                        
                        for _, row in df.iterrows():
                            nm = row['이름']; assigned = str(row.get(cp, '')).strip()
                            if not assigned: continue
                            p_obj = row.to_dict(); p_obj['assigned_pos'] = assigned
                            
                            w1 = str(row.get('1순위', '')).strip(); w2 = str(row.get('2순위', '')).strip(); w3 = str(row.get('3순위', '')).strip()
                            if assigned == '대기': mt = 'wait'
                            elif assigned == w1: mt = '1st'
                            elif assigned == w2: mt = '2nd'
                            elif assigned == w3: mt = '3rd'
                            else: mt = 'random'
                            p_obj['match_type'] = mt
                            
                            if row[ct] == "A팀": ta.append(p_obj)
                            else: tb.append(p_obj)
                            
                            # 상태 업데이트
                            if mt == '1st': d_hist[nm] += 1
                            if mt == 'wait': d_hard[nm] += 10
                            elif mt == '3rd': d_hard[nm] += 5
                            elif mt in ['2nd', 'random']: d_hard[nm] += 3
                        res[r] = (ta, tb)
                    st.session_state['fair_results'] = res

            if st.button("🎲 라인업 생성 (새로고침)"):
                with st.spinner("계산 중..."): 
                    st.session_state['fair_results'] = generate_vega_priority_schedule(df)
                    st.success("완료!")
                    st.rerun()
                    
            if 'fair_results' in st.session_state:
                for r_num, (team_a, team_b) in st.session_state['fair_results'].items():
                    st.write(f"#### {r_num*2-1}·{r_num*2} 세트")
                    c1, c2 = st.columns(2)
                    c1.success(f"A팀 ({len([p for p in team_a if p['assigned_pos']!='대기'])}명)")
                    for p in team_a: 
                        if p['assigned_pos']!='대기': c1.write(f"- **{p['assigned_pos']}**: {p['이름']} ({p.get('match_type')})")
                    c2.info(f"B팀 ({len([p for p in team_b if p['assigned_pos']!='대기'])}명)")
                    for p in team_b: 
                        if p['assigned_pos']!='대기': c2.write(f"- **{p['assigned_pos']}**: {p['이름']} ({p.get('match_type')})")
                    bench = [p for p in team_a+team_b if p['assigned_pos']=='대기']
                    if bench: st.caption(f"대기: {', '.join([p['이름'] for p in bench])}")
                    st.divider()

            if st.button("저장 (공개)"):
                final_df = df.copy()
                if 'fair_results' in st.session_state:
                    for r_num, (ta, tb) in st.session_state['fair_results'].items():
                        for p in ta: 
                            final_df.loc[final_df['이름']==p['이름'], f'확정{r_num}'] = p['assigned_pos']
                            final_df.loc[final_df['이름']==p['이름'], f'팀{r_num}'] = 'A팀'
                        for p in tb: 
                            final_df.loc[final_df['이름']==p['이름'], f'확정{r_num}'] = p['assigned_pos']
                            final_df.loc[final_df['이름']==p['이름'], f'팀{r_num}'] = 'B팀'
                update_lineup(final_df)
                st.success("저장되었습니다.")

# --- 탭 7: 관리자 ---
with tab7:
    st.header("관리자 메뉴")
    admin_auth = st.empty()
    if not st.session_state['admin_logged_in']:
        with admin_auth.form("admin_main_login"):
            pw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("확인"):
                if pw == ADMIN_PASSWORD: st.session_state['admin_logged_in'] = True; admin_auth.empty()
                else: st.error("비밀번호 불일치")
    
    if st.session_state['admin_logged_in']:
        st.subheader("✅ 참가 확인 관리")
        apps = load_applicants()
        if apps:
            df_manage = pd.DataFrame(apps)
            if '입금' not in df_manage.columns: df_manage['입금'] = 'X'
            df_manage['입금_bool'] = df_manage['입금'].apply(lambda x: True if str(x).upper() == 'O' else False)
            cols_manage = ["이름", "연락처", "입금_bool", "1순위"]
            edited_manage = st.data_editor(df_manage[cols_manage], column_config={"입금_bool": st.column_config.CheckboxColumn("참가 확인")}, hide_index=True)
            if st.button("참가 현황 저장"):
                df_manage.update(edited_manage)
                df_manage['입금'] = df_manage['입금_bool'].apply(lambda x: 'O' if x else 'X')
                update_lineup(df_manage)
                st.success("저장되었습니다.")
                time.sleep(1.0)
                st.rerun()
        else: st.info("신청자 없음")

        st.divider()
        with st.expander("📞 연락처 복사"):
            if apps: st.code(", ".join([p.get('연락처') for p in apps if p.get('연락처')]))

st.markdown("---")
st.markdown("<div style='text-align: center; color: gray; font-size: small;'>Designed by <b>Heeseong</b></div>", unsafe_allow_html=True)
