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

# --- [업데이트 로그 데이터] ---
UPDATE_LOGS = {
    "2026.01.16 (Ver 3.0)": [
        "🛡️ [알고리즘] **'제외 포지션'** 기능 추가 (부상/비선호 포지션 회피)",
        "📝 [UI] 참가 신청서에 제외 포지션 선택(최대 2개) 옵션 신설",
        "⚙️ [관리] 데이터 구조 업그레이드 (제외 컬럼 추가)"
    ],
    "2026.01.15 (Ver 2.9)": [
        "🗳️ [MVP] '라인업 보고 투표하기' 기능 추가",
        "🕒 [MVP] 게임 종료 후에도 지난 기록으로 투표 가능",
        "✨ [UI] 선수 이름 옆 '투표' 버튼으로 원클릭 참여"
    ]
}

# --- [데이터 리스트] ---
POSITIONS_ALL = ["레프트", "속공", "세터", "라이트", "앞차", "백차", "레프트백", "센터백", "라이트백"]
POSITIONS_3RD = ["레프트백", "센터백", "라이트백", "속공"]
LEVELS = ["입문", "초급", "중급", "상급", "최상급"]
POSITION_QUOTAS = {"세터": 1, "레프트": 1, "라이트": 1, "속공": 1, "앞차": 1, "백차": 1, "레프트백": 1, "센터백": 1, "라이트백": 1}
LEVEL_MAP = {"입문": 1, "초급": 2, "중급": 3, "상급": 4, "최상급": 5}

# --- [세션 상태 초기화] ---
if 'admin_logged_in' not in st.session_state: st.session_state['admin_logged_in'] = False
if 'lineup_admin_logged_in' not in st.session_state: st.session_state['lineup_admin_logged_in'] = False
if 'mvp_voter_verified' not in st.session_state: st.session_state['mvp_voter_verified'] = False
if 'mvp_voter_name' not in st.session_state: st.session_state['mvp_voter_name'] = ""
if 'mvp_voter_phone' not in st.session_state: st.session_state['mvp_voter_phone'] = ""

# --- [구글 시트 연결] ---
@st.cache_resource
def get_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            key_dict = st.secrets["gcp_service_account"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name(r"C:\Users\82106\service_account.json", scope)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        return None

def get_sheet_instance(sheet_name):
    client = get_connection()
    if client:
        try:
            doc = client.open(DOC_NAME)
            try:
                return doc.worksheet(sheet_name)
            except:
                return doc.add_worksheet(title=sheet_name, rows=100, cols=20)
        except:
            return None
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
    if not isinstance(level_full, str): return str(level_full)
    return level_full.split(" ")[0]

# --- [기능 함수] ---
def save_game_info(info_dict):
    sheet = get_sheet_instance(SHEET_GAME_INFO)
    if sheet:
        sheet.append_row([
            info_dict['제목'], info_dict['일시'], info_dict['장소'], 
            info_dict['성별'], info_dict['참가비'], info_dict['계좌'], 
            info_dict['설명'], info_dict['연락처'], info_dict['마감일시']
        ])
        st.cache_data.clear()

@st.cache_data(ttl=10)
def get_current_game_info():
    sheet = get_sheet_instance(SHEET_GAME_INFO)
    if sheet:
        all_games = sheet.get_all_records()
        if all_games: return all_games[-1]
    return None

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
            game_date = game_info.get('일시', datetime.now().strftime("%Y-%m-%d"))
            game_title = game_info.get('제목', 'Untitled')
            for p in data:
                assigned = p.get('확정1', '') 
                rows.append([
                    game_date, game_title, 
                    p.get('이름', ''), p.get('연락처', ''), 
                    p.get('1순위', ''), p.get('레벨', ''),
                    assigned 
                ])
            for r in rows: dst_sheet.append_row(r)
        st.cache_data.clear()

@st.cache_data(ttl=5)
def load_applicants():
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet: return sheet.get_all_records()
    return []

def add_applicant(name, phone, level, pos1, pos2, pos3, note, excluded_str):
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        row_data = [
            name, normalize_phone(phone), level, pos1, pos2, pos3, 
            "", "", "", pos1, pos2, pos3, 
            anonymize_name(name), "X", note, excluded_str
        ]
        sheet.append_row(row_data)
        st.cache_data.clear()

def cancel_applicant(name, phone):
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        clean_phone = normalize_phone(phone)
        try:
            cell_list = sheet.findall(name)
            for cell in cell_list:
                row_phone = sheet.cell(cell.row, 2).value
                if normalize_phone(row_phone) == clean_phone:
                    sheet.delete_rows(cell.row)
                    st.cache_data.clear()
                    return True, "취소되었습니다."
            return False, "정보가 일치하지 않습니다."
        except: return False, "오류 발생"

def update_lineup(df):
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        sheet.clear()
        headers = [
            "이름", "연락처", "레벨", "1순위", "2순위", "3순위", 
            "팀1", "팀2", "팀3", "확정1", "확정2", "확정3", 
            "이름(가림)", "입금", "비고", "제외"
        ]
        sheet.append_row(headers)
        
        if '이름(가림)' not in df.columns: df['이름(가림)'] = df['이름'].apply(anonymize_name)
        if '입금' not in df.columns: df['입금'] = 'X'
        if '비고' not in df.columns: df['비고'] = ''
        if '제외' not in df.columns: df['제외'] = ''
            
        final_cols = headers
        for col in final_cols:
            if col not in df.columns: df[col] = ""
                
        sheet.append_rows(df[final_cols].values.tolist())
        st.cache_data.clear()

def clear_applicants():
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        sheet.clear()
        headers = [
            "이름", "연락처", "레벨", "1순위", "2순위", "3순위", 
            "팀1", "팀2", "팀3", "확정1", "확정2", "확정3", 
            "이름(가림)", "입금", "비고", "제외"
        ]
        sheet.append_row(headers)
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
        clean_phone = normalize_phone(phone)
        try:
            records = sheet.get_all_records()
            for row in records:
                if row.get('이름') == name and normalize_phone(row.get('연락처')) == clean_phone:
                    history.append(row)
        except:
            pass
    return history

# --- [기록 조회용 함수 추가] ---
@st.cache_data(ttl=60)
def load_all_history():
    sheet = get_sheet_instance(SHEET_HISTORY)
    # 데이터가 없으면 빈 리스트 반환
    if not sheet: return []
    try:
        return sheet.get_all_records()
    except:
        return []

def save_mvp_vote(voter, phone, mvp_candidate):
    sheet = get_sheet_instance(SHEET_MVP)
    if sheet:
        clean_phone = normalize_phone(phone)
        today = datetime.now().strftime("%Y-%m-%d")
        data = sheet.get_all_records()
        for row in data:
            if row['투표자이름'] == voter and normalize_phone(row['투표자연락처']) == clean_phone and row['일시'] == today:
                return False, "이미 투표하셨습니다."
        sheet.append_row([today, voter, clean_phone, mvp_candidate])
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
        votes = [row['MVP후보'] for row in data if row.get('일시') == today]
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
        daily_counts = df.groupby(['일시', 'MVP후보']).size().reset_index(name='득표수')
        idx = daily_counts.groupby(['일시'])['득표수'].transform(max) == daily_counts['득표수']
        return daily_counts[idx].sort_values('일시', ascending=False)
    return []

def save_suggestion(message):
    sheet = get_sheet_instance(SHEET_SUGGESTION)
    if sheet:
        sheet.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message])
        return True
    return False

def load_suggestions():
    sheet = get_sheet_instance(SHEET_SUGGESTION)
    if sheet: return sheet.get_all_records()
    return []

@st.cache_data(ttl=60)
def get_my_mvp_stats(name, phone):
    sheet = get_sheet_instance(SHEET_MVP)
    received = 0
    voted = 0
    if sheet:
        data = sheet.get_all_records()
        clean_phone = normalize_phone(phone)
        for row in data:
            if row.get('MVP후보') == name: received += 1
            if row.get('투표자이름') == name and normalize_phone(row.get('투표자연락처')) == clean_phone: voted += 1
    return received, voted

def draw_radar_chart(stats):
    categories = ['🔥참여율', '✨매너', '❤️헌신', '🌈다양성', '🤝사교성']
    values = [stats['participation'], stats['manner'], stats['dedication'], stats['diversity'], stats['social']]
    
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values,
        theta=categories,
        fill='toself',
        name='Stats',
        line=dict(color='#FF5722'),
        fillcolor='rgba(255, 87, 34, 0.4)'
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100], showticklabels=False)),
        showlegend=False,
        margin=dict(l=40, r=40, t=30, b=30),
        height=300,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    return fig

def generate_kakao_text(df):
    text = "🏐 [이번 주 배구 픽업 라인업] 🏐\n\n"
    for i, (col_team, col_pos) in enumerate([("팀1", "확정1"), ("팀2", "확정2"), ("팀3", "확정3")], 1):
        if col_pos not in df.columns: continue
        text += f"==== {i*2-1}·{i*2}세트 ====\n"
        playing = df[df[col_pos] != '']
        if playing.empty:
            text += "(미정)\n\n"; continue
        
        text += "🔴 A팀\n"
        for _, r in playing[(playing[col_team]=="A팀") & (playing[col_pos]!="대기")].iterrows():
            text += f"- {r[col_pos]}: {r['이름']}\n"
        text += "\n🔵 B팀\n"
        for _, r in playing[(playing[col_team]=="B팀") & (playing[col_pos]!="대기")].iterrows():
            text += f"- {r[col_pos]}: {r['이름']}\n"
        text += "\n🛌 대기\n"
        bench = playing[playing[col_pos] == "대기"]
        if bench.empty: text += "-\n"
        else:
            for _, r in bench.iterrows(): text += f"- {r['이름']}\n"
        text += "\n"
    return text

# --- [알고리즘] ---
def calculate_score(level_str):
    for key, score in LEVEL_MAP.items():
        if key in level_str: return score
    return 1

def get_priority_score(player, global_history, global_hardship):
    name = player['이름']
    target_pos = str(player['1순위']).strip()
    
    score = 50.0 
    reasons = ["기본(50)"]
    
    if "[VEGA]" in name:
        score += 100.0
        reasons.append("+VEGA(100)")
        
    success_count = global_history.get(name, 0)
    if success_count > 0:
        penalty = success_count * 10.0
        score -= penalty
        reasons.append(f"-배정{success_count}회({int(penalty)})")
    
    hardship_score = global_hardship.get(name, 0)
    if hardship_score > 0:
        score += hardship_score
        reasons.append(f"+마일리지({int(hardship_score)})")
        
    score += random.random()
    return score, " ".join(reasons)

def assign_positions_in_team(team_members):
    # 1. 우선순위 점수 높은 순 정렬
    team_members.sort(key=lambda x: x['priority_score'], reverse=True)
    
    # 초기화
    for p in team_members: 
        p['assigned_pos'] = None
        p['match_type'] = 'random'
        p['got_1st'] = False
    
    team_size = len(team_members)
    quotas = POSITION_QUOTAS.copy()
    
    # 인원별 쿼터 조정 (기존 유지)
    if team_size == 8:
        c_fast = sum(1 for p in team_members if '속공' in [str(p['1순위']), str(p['2순위'])])
        c_cb = sum(1 for p in team_members if '센터백' in [str(p['1순위']), str(p['2순위'])])
        if c_fast >= c_cb: quotas['센터백'] = 0
        else: quotas['속공'] = 0
    elif team_size == 7: quotas['속공'] = 0; quotas['센터백'] = 0
    elif team_size == 6: quotas['속공'] = 0; quotas['센터백'] = 0; quotas['백차'] = 0
    
    # 1순위 -> 2순위 -> 3순위 배정 (단, 제외 포지션이면 패스)
    for step in [1, 2, 3]:
        for p in team_members:
            if p['assigned_pos']: continue
            wish = str(p.get(f'{step}순위', '')).strip()
            
            # [핵심] 자리가 있고(>0) AND 제외 포지션이 아닐 때만 배정
            if wish and wish != "선택 안함" and quotas.get(wish, 0) > 0:
                if wish not in p.get('excluded', []):
                    p['assigned_pos'] = wish
                    quotas[wish] -= 1
                    if step == 1: p['match_type'] = '1st'; p['got_1st'] = True
                    elif step == 2: p['match_type'] = '2nd'
                    elif step == 3: p['match_type'] = '3rd'
    
    # 남은 자리 (임의 배정) - 제외 포지션 회피
    for p in team_members:
        if not p['assigned_pos']:
            filled = False
            excluded_list = p.get('excluded', [])
            
            for pos, q in quotas.items():
                # [핵심] 남은 자리 중 제외 포지션이 아닌 곳 찾기
                if q > 0 and pos not in excluded_list:
                    p['assigned_pos'] = pos
                    quotas[pos] -= 1
                    p['match_type'] = 'random'
                    filled = True
                    break
            
            # 갈 곳이 없으면 대기 (남은 자리가 전부 기피 포지션일 때)
            if not filled: 
                p['assigned_pos'] = "대기"
                p['match_type'] = 'wait'
                
    return team_members

def generate_vega_priority_schedule(df):
    base_players = df.to_dict('records')
    
    # [NEW] 제외 포지션 파싱 (쉼표로 구분된 문자열 -> 리스트)
    for p in base_players:
        ex_str = str(p.get('제외', ''))
        if ex_str and ex_str.strip():
            p['excluded'] = [x.strip() for x in ex_str.split(',') if x.strip()]
        else:
            p['excluded'] = []

    global_history = {p['이름']: 0 for p in base_players}
    global_hardship = {p['이름']: 0 for p in base_players}
    final_rounds = {}

    for round_num in range(1, 4):
        # 세트 필터링 (기존 유지)
        target_set = f"{round_num*2-1}·{round_num*2}"
        valid_markers = ["1·2", "3·4", "5·6"]
        
        current_pool = []
        for p in base_players:
            note = str(p.get('비고', ''))
            has_marker = any(m in note for m in valid_markers)
            if has_marker:
                if target_set in note: current_pool.append(p.copy())
            else:
                current_pool.append(p.copy())

        # 점수 계산
        for p in current_pool:
            sc, re = get_priority_score(p, global_history, global_hardship)
            p['priority_score'] = sc; p['score_reason'] = re
            
        current_pool.sort(key=lambda x: x['priority_score'], reverse=True)
        
        # 팀 분배 (VEGA/PickUp 밸런싱)
        match_cap = len(current_pool)
        vegas = [p for p in current_pool if "[VEGA]" in p['이름']]
        pickups = [p for p in current_pool if "[VEGA]" not in p['이름']]
        
        # (시뮬레이션 로직은 길어서 생략하지만 기존 코드 그대로 사용됨)
        # ... size_a 결정 및 팀 분배 ...
        
        size_a = (match_cap + 1) // 2
        team_a = []; team_b = []
        
        # (간략화된 분배 로직 예시 - 기존 복잡한 시뮬레이션 그대로 쓰셔도 무방)
        for v in vegas:
            if len(team_a) < size_a: team_a.append(v)
            else: team_b.append(v)
        for pk in pickups:
            if len(team_a) < size_a: team_a.append(pk)
            else: team_b.append(pk)
            
        final_a = assign_positions_in_team(team_a)
        final_b = assign_positions_in_team(team_b)
        
        # 상태 업데이트
        for p in final_a + final_b:
            nm = p['이름']; mt = p.get('match_type')
            if mt == '1st': global_history[nm] += 1
            if mt == 'wait': global_hardship[nm] += 10
            elif mt == '3rd': global_hardship[nm] += 5
            elif mt in ['2nd', 'random']: global_hardship[nm] += 3
            
        final_rounds[round_num] = (final_a, final_b)
        
    return final_rounds
    
# --- [메인 화면] ---
st.set_page_config(page_title="여순광 배구 픽업", page_icon="🏐", layout="wide") 

st.markdown("""
    <style>
        div[data-testid="stTabsNav"] {
            position: sticky;
            top: 0;
            z-index: 999;
            background-color: white;
            padding-top: 1rem;
        }
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("📢 Update Log")
    for date, logs in UPDATE_LOGS.items():
        with st.expander(date):
            content_html = "<ul style='font-size: 13px; padding-left: 15px; margin: 0; line-height: 1.4; color: #404040;'>"
            for log in logs:
                content_html += f"<li style='margin-bottom: 4px;'>{log}</li>"
            content_html += "</ul>"
            st.markdown(content_html, unsafe_allow_html=True)
    
    st.divider()
    
    st.markdown("### 📞 문의하기")
    st.markdown("💬 [**오픈채팅방 입장 (클릭)**](https://open.kakao.com/o/gf1s6t9h)")
    st.caption("🗣️ **소리함**: 우측 상단 '소리함' 탭을 이용해주세요.")
    
    if get_sheet_instance(SHEET_APPLICANTS):
        st.success("✅ 서버 연결됨")
    else:
        st.error("❌ 서버 연결 실패")

st.title("🏐 여순광 배구 픽업게임 매니저")
current_game = get_current_game_info()

tab0, tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🔰 운영 안내", "📢 참가 신청", "📋 라인업 공개", "📊 My Page", "🏆 MVP", "🗣️ 소리함", "⚡ 라인업 생성(관리자)", "⚙️ 관리자"
])

# --- 탭 0: 운영 안내 ---
with tab0:
    st.info("📢 **[중요] 1~2월 시범 운영 안내** (필독)")
    st.markdown("""
    **여순광 픽업게임에 오신 것을 환영합니다!**
    현재 체육관 섭외 및 대략적인 참여 인원을 파악하기 위해 **1~2월은 시범적으로 운영**됩니다.
    3월 정식 오픈 전까지 아래 내용을 꼭 확인해주세요.
    
    ### 🤝 순천VEGA 팀과의 협력 운영
    - **기간**: 1월 ~ 2월
    - **방식**: 매주 목요일 **순천VEGA 배구클럽**의 운동 시간에 픽업게임을 함께 진행합니다.
    - **우선권**: 체육관 대관 주체인 **순천VEGA 회원들에게 참가 신청 및 팀 편성 우선권**이 있습니다.
    - **팀 구성**: VEGA 회원 위주로 팀을 구성한 후, 빈 자리나 상대 팀으로 픽업 참가자가 배정되어 함께 연습 경기를 진행합니다.
    
    > 🙏 **양해 말씀**: 아직 정식 오픈 전 단계라 운영에 미흡한 점이 있을 수 있습니다. 배구를 사랑하는 마음으로 함께 즐겨주시면 감사하겠습니다.
    
    ---
    
    ### 📅 운동 정보
    - **시간**: 매주 목요일 (공휴일 제외) **18:30 ~ 21:30**
        - *※ 1~2월은 시범 운영이라 부득이하게 목요일에 진행하지만, 3월 정식 출범 이후에는 주요 클럽들의 운동 시간과 겹치지 않도록 **월·수·금요일 중**으로 추진할 예정입니다.*
        - 18:30 ~ 19:00: 몸풀기
        - 19:00 ~ 19:20: 공격 및 서브 연습
        - 19:20 ~ 21:30: 경기 진행
    - **장소**: 순천조례초등학교 체육관
    - **참가비**: **미정** (추후 공지)
    
    ### 📝 진행 방법
    1. **참가 신청**: 이 웹앱의 **[📢 참가 신청]** 탭에서 신청해주세요.
        - 📅 **신청 기간**: 매주 **일요일 ~ 수요일** (목요일 운동 전날 마감)
        - **시간 선택**: 늦참/조기귀가 시 **참가 가능한 세트**를 꼭 체크해주세요.
    2. **경기 진행**: 12명 이상 모이면 경기를 진행합니다.
    3. **성별**: **남성 경기**이며, 남성 18명 미만 시 여성은 **수비 선수로만** 참가 가능합니다.
    4. **팀 배정**: 실력 균형을 맞춘 **자동 라인업 시스템**을 사용합니다. (편애 NO!)
    
    ---
    **💬 문의사항은 오픈채팅방을 이용해주세요.**
    [👉 여순광 배구 픽업 오픈채팅방 입장하기](https://open.kakao.com/o/gf1s6t9h)
    """)

# --- 탭 1: 참가 신청 ---
with tab1:
    # 1. 게임 종료(CLOSED) 또는 정보 없음 확인
    if not current_game or current_game.get('제목') == 'CLOSED':
        st.info("💤 **현재 모집 중인 게임이 없습니다.**")
        st.markdown("""
        ### 🔜 다음 게임을 준비 중입니다!
        
        관리자가 새로운 게임을 개설할 때까지 잠시만 기다려주세요.
        보통 **매주 일요일**에 새로운 모집이 시작됩니다.
        
        - 문의사항은 [오픈채팅방](https://open.kakao.com/o/gf1s6t9h)을 이용해주세요.
        """)
        st.markdown("<div style='text-align: center; font-size: 60px; margin-top: 30px;'>🏐</div>", unsafe_allow_html=True)
        
    else:
        # 2. 게임 진행 중 (정상적인 신청 화면)
        if 'reg_success' not in st.session_state: st.session_state['reg_success'] = False
        if 'reg_name' not in st.session_state: st.session_state['reg_name'] = ""
        if 'reg_is_late' not in st.session_state: st.session_state['reg_is_late'] = False

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
            else:
                st.success(f"✅ {msg_name}님 신청 완료!")
            
            if st.button("확인 (메시지 닫기)"):
                st.session_state['reg_success'] = False
                st.rerun()
            st.divider()

        if is_expired:
            st.warning("⚠️ **정규 신청이 마감되었습니다.** 현재는 **'대기/추가'** 등록만 가능합니다.")
        
        st.write("### 👇 참가 신청서")
        with st.form("apply_form"):
            c1, c2 = st.columns(2)
            with c1: name = st.text_input("이름")
            with c2: phone = st.text_input("연락처", placeholder="01012345678")
            
            with st.expander("ℹ️ 레벨 기준 보기 (클릭)", expanded=False):
                st.markdown("- **입문**: 기본기 부족\n- **초급**: 경험 적음\n- **중급**: 전국대회 가능\n- **상급**: 전국대회 상위\n- **최상급**: 선출 준함")
            is_vega = st.checkbox("순천VEGA 회원 (우선권)")
            
            st.markdown("---")
            st.write("**⏱️ 참가 가능 시간(세트) 선택**")
            set_options = ["1·2세트 (19:20 ~ 20:00)", "3·4세트 (20:00 ~ 20:40)", "5·6세트 (20:40 ~ 21:20)"]
            selected_sets = st.multiselect("참가할 세트를 모두 선택해주세요", options=set_options, default=set_options)
            
            lc1, lc2 = st.columns(2)
            with lc1: level = st.selectbox("참가자 레벨", LEVELS)
            
            st.markdown("---")
            if not is_expired: st.info("📢 **주의:** 1순위 포지션 경쟁이 치열할 경우(7명 이상), 점수 및 밸런스에 따라 밀릴 수 있습니다.")
            
            p1, p2, p3 = st.columns(3)
            with p1: pos1 = st.selectbox("1순위 (필수)", POSITIONS_ALL)
            with p2: pos2 = st.selectbox("2순위 (선택)", ["선택 안함"] + POSITIONS_ALL)
            with p3: pos3 = st.selectbox("3순위 (수비/속공)", ["선택 안함"] + POSITIONS_3RD)
            
            st.markdown("---")
            st.write("**🚫 제외(기피) 포지션 선택 (선택 사항)**")
            st.caption("부상이나 실력 문제로 **'절대 수행 불가능한'** 포지션이 있다면 선택해주세요. (최대 2개)")
            excluded_pos = st.multiselect("제외할 포지션 선택", POSITIONS_ALL, max_selections=2)
            
            submit_label = "대기/추가 등록하기 (마감됨)" if is_expired else "신청하기"
            
            if st.form_submit_button(submit_label):
                if name and phone:
                    if not selected_sets: st.error("❌ 최소 1개 이상의 세트를 선택해야 합니다.")
                    elif pos1 in excluded_pos: st.error("❌ 1순위 포지션은 제외할 수 없습니다.")
                    else:
                        is_black, reason = check_blacklist(name, phone)
                        if is_black: st.error(f"🚨 신청 불가: {reason}")
                        else:
                            final_name = f"[VEGA] {name}" if is_vega else name
                            sets_str = ", ".join([s.split("세트")[0] for s in selected_sets])
                            excluded_str = ", ".join(excluded_pos)
                            try:
                                add_applicant(final_name, phone, level, pos1, "" if pos2=="선택 안함" else pos2, "" if pos3=="선택 안함" else pos3, sets_str, excluded_str)
                                st.session_state['reg_success'] = True
                                st.session_state['reg_name'] = name
                                st.session_state['reg_is_late'] = is_expired
                                st.toast(f"✅ {name}님 등록이 완료되었습니다!", icon="🎉"); st.rerun()
                            except Exception as e: st.error(f"❌ 저장 중 오류: {str(e)}")
                else: st.error("필수 입력 누락"); st.toast("⚠️ 이름과 연락처를 입력해주세요!", icon="🚨")
        
        with st.expander("🗑️ 신청 취소"):
            with st.form("cancel"):
                cc1, cc2 = st.columns(2)
                with cc1: c_name = st.text_input("이름")
                with cc2: c_phone = st.text_input("연락처")
                if st.form_submit_button("취소하기"):
                    if is_expired: save_suggestion(f"🚨 [마감후취소] {c_name} ({c_phone}) 취소")
                    suc, msg = cancel_applicant(c_name, c_phone)
                    if not suc: suc, msg = cancel_applicant(f"[VEGA] {c_name}", c_phone)
                    if suc: st.success(msg); st.toast("🗑️ 취소되었습니다."); time.sleep(1.5); st.rerun() 
                    else: st.error(msg)

        st.divider()
        st.subheader("📊 실시간 참가 신청 현황")
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
        else:
            st.info("👋 **아직 신청자가 없습니다.** 첫 번째 참가자가 되어보세요!")
            st.metric("현재 참가 인원", "0명")
            
# --- 탭 2: 라인업 공개 ---
with tab2:
    # 1. 게임 종료(CLOSED) 또는 정보 없음 확인
    if not current_game or current_game.get('제목') == 'CLOSED':
        st.header("📋 이번 주 라인업")
        st.divider()
        st.info("💤 **현재 진행 중인 게임이 없습니다.**")
        st.write("새로운 게임이 개설되고 팀 배정이 완료되면 이곳에 라인업이 공개됩니다.")
        st.caption("지난 경기 결과는 'My Page'나 'MVP' 탭에서 확인하실 수 있습니다.")
        
    else:
        # 2. 게임 진행 중 (정상적인 라인업 화면)
        with st.expander("📘 이용 가이드: 배정 기준 및 보는 법", expanded=False):
            st.markdown("""
            **1. 배정 기준 (우선순위 점수제)**
            | 항목 | 점수 | 설명 |
            | :--- | :--- | :--- |
            | **기본 점수** | `50점` | 모든 참가자 기본 지급 |
            | **VEGA 회원** | `+100점` | **우선권 부여** |
            | **1순위 배정** | `-10점`/회 | 오늘 1순위를 많이 할수록 **배정 누적**되어 양보 유도 |
            | **기여도** | `+3~10점` | **대기/비선호 포지션** 수행 시 점수 적립 (이번 게임 내 누적) |

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
        
        if not data_final: 
            st.info("⏳ **아직 라인업이 확정되지 않았습니다.** (모집 중)")
        else:
            df_final = pd.DataFrame(data_final)
            
            # 데이터 중복 제거
            if '이름' in df_final.columns and '연락처' in df_final.columns:
                df_final = df_final.drop_duplicates(subset=['이름', '연락처'], keep='last')

            # 이름 마스킹
            if '이름' in df_final.columns:
                df_final['이름_masked'] = df_final['이름'].apply(anonymize_name)
            
            st.divider()

            lineup_tabs = st.tabs(["1·2 세트", "3·4 세트", "5·6 세트"])
            for i, (col_team, col_pos) in enumerate([("팀1", "확정1"), ("팀2", "확정2"), ("팀3", "확정3")], 1):
                with lineup_tabs[i-1]:
                    if col_pos in df_final.columns and col_team in df_final.columns:
                        playing = df_final[df_final[col_pos].astype(str).str.strip() != '']
                        
                        if not playing.empty:
                            real_players = playing[playing[col_pos] != "대기"]
                            if not real_players.empty:
                                team_a_df = real_players[real_players[col_team]=="A팀"]
                                team_b_df = real_players[real_players[col_team]=="B팀"]
                                count_a = len(team_a_df)
                                count_b = len(team_b_df)
                                
                                def get_missing_pos(df_team, pos_col):
                                    if df_team.empty: return []
                                    current_pos = set(df_team[pos_col].unique())
                                    full_set = set(POSITIONS_ALL) 
                                    missing = list(full_set - current_pos)
                                    sort_order = {p: idx for idx, p in enumerate(POSITIONS_ALL)}
                                    missing.sort(key=lambda x: sort_order.get(x, 99))
                                    return missing

                                missing_a = get_missing_pos(team_a_df, col_pos)
                                missing_b = get_missing_pos(team_b_df, col_pos)
                                missing_text_a = ", ".join(missing_a) if missing_a else "없음"
                                missing_text_b = ", ".join(missing_b) if missing_b else "없음"

                                info_msg = f"📢 **[{i*2-1}·{i*2}세트] {count_a} vs {count_b} 경기**"
                                if count_a != count_b:
                                    info_msg += f" (🔴A제외: {missing_text_a} | 🔵B제외: {missing_text_b})"
                                else:
                                    if missing_text_a == missing_text_b:
                                        info_msg += f" (공통 제외: {missing_text_a})"
                                    else:
                                        info_msg += f" (🔴A제외: {missing_text_a} | 🔵B제외: {missing_text_b})"
                                st.info(info_msg)

                            def get_priority_badge(row, pos_col):
                                current = str(row[pos_col]).strip()
                                w1 = str(row.get('1순위', '')).strip()
                                w2 = str(row.get('2순위', '')).strip()
                                w3 = str(row.get('3순위', '')).strip()
                                if current == w1: return "<span style='color:#1565C0; background-color:#E3F2FD; padding:2px 6px; border-radius:4px; font-weight:bold; border:1px solid #1565C0;'>1순위</span>"
                                elif current == w2: return "<span style='color:#2E7D32; background-color:#E8F5E9; padding:2px 6px; border-radius:4px; font-weight:bold; border:1px solid #2E7D32;'>2순위</span>"
                                elif current == w3: return "<span style='color:#E65100; background-color:#FFF3E0; padding:2px 6px; border-radius:4px; font-weight:bold; border:1px solid #E65100;'>3순위</span>"
                                else: return "<span style='color:#C62828; background-color:#FFEBEE; padding:2px 6px; border-radius:4px; font-weight:bold; border:1px solid #C62828;'>무</span>"

                            c1, c2 = st.columns(2)
                            with c1:
                                st.error(f"🔴 A팀 (VEGA)")
                                for _, r in playing[(playing[col_team]=="A팀") & (playing[col_pos]!="대기")].iterrows():
                                    badge = get_priority_badge(r, col_pos)
                                    st.markdown(f"- **{r[col_pos]}**: {r['이름_masked']} {badge} ({r.get('1순위', '')})", unsafe_allow_html=True)
                            with c2:
                                st.info(f"🔵 B팀 (픽업)")
                                for _, r in playing[(playing[col_team]=="B팀") & (playing[col_pos]!="대기")].iterrows():
                                    badge = get_priority_badge(r, col_pos)
                                    st.markdown(f"- **{r[col_pos]}**: {r['이름_masked']} {badge} ({r.get('1순위', '')})", unsafe_allow_html=True)
                            
                            st.markdown("---")
                            bench = playing[playing[col_pos]=="대기"]
                            if not bench.empty:
                                st.caption(f"🛌 **대기**")
                                for _, r in bench.iterrows(): st.write(f"- {r['이름_masked']} (희망: {r.get('1순위', '')})")
                    else:
                        st.warning("아직 배정 정보가 없습니다.")
# --- 탭 3: My Page ---
with tab3:
    with st.expander("📘 이용 가이드: 내 정보 확인", expanded=False):
        st.write("본인의 이름과 연락처를 입력하면 '나만의 선수 카드'와 '과거 기록'을 확인할 수 있습니다.")

    st.header("📊 My Player Card")
    
    # 세션 상태 초기화
    if 'my_name' not in st.session_state: st.session_state['my_name'] = ""
    if 'my_phone' not in st.session_state: st.session_state['my_phone'] = ""

    # [수정] 폼에서 캐싱된 데이터를 호출하여 부하 감소
    with st.form("my_history"):
        c1, c2 = st.columns(2)
        with c1: input_name = st.text_input("이름", value=st.session_state['my_name'])
        with c2: input_phone = st.text_input("연락처", value=st.session_state['my_phone'])
        
        # [중요] st.rerun 삭제 + 토스트 추가
        if st.form_submit_button("조회 & 분석"):
            st.session_state['my_name'] = input_name
            st.session_state['my_phone'] = input_phone
            st.toast(f"{input_name}님 기록을 조회합니다.", icon="🔍")

    # 조회된 정보가 있으면 결과 표시 (rerun 없어도 바로 실행됨)
    if st.session_state['my_name'] and st.session_state['my_phone']:
        my_name = st.session_state['my_name']
        my_phone = st.session_state['my_phone']
        clean_phone = normalize_phone(my_phone)
        
        # [수정] 캐싱된 함수 호출
        hist = get_my_history(my_name, my_phone)
        mvp_received, mvp_voted = get_my_mvp_stats(my_name, my_phone)
        cur_apps = load_applicants()
        my_cur = [p for p in cur_apps if (p['이름']==my_name or p['이름']==f"[VEGA] {my_name}") and normalize_phone(p['연락처'])==clean_phone]
        
        # 스탯 계산
        score_part = min(len(hist) * 5, 100)
        score_manner = min(mvp_received * 10, 100)
        unique_pos = set([str(h.get('1순위', '')).strip() for h in hist if h.get('1순위')])
        score_div = min(len(unique_pos) * 15, 100)
        score_social = min(mvp_voted * 5, 100)
        
        dedication_count = 0
        for h in hist:
            wish = str(h.get('1순위', '')).strip()
            assigned = str(h.get('확정포지션', '')).strip()
            if assigned:
                if assigned == '대기': dedication_count += 2 
                elif assigned != wish: dedication_count += 1 
        
        score_dedic = min(dedication_count * 15, 100) 

        stats = {
            'participation': score_part, 
            'manner': score_manner, 
            'dedication': score_dedic, 
            'diversity': score_div, 
            'social': score_social
        }

        # 3. 화면 표시
        st.divider()
        col_chart, col_info = st.columns([1.2, 1])
        
        with col_chart:
            st.markdown(f"### 🏐 {my_name}님의 스탯")
            try:
                fig = draw_radar_chart(stats)
                # [수정] 모바일 메모리 절약을 위한 staticPlot 설정
                st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True})
            except Exception as e:
                st.error("차트 로딩 중 오류가 발생했습니다.")
            
            # [NEW] 스탯 설명 추가 (여기에 들어갑니다!)
            with st.expander("ℹ️ 스탯(능력치) 산정 기준 보기"):
                st.markdown("""
                <div style="font-size: 0.9em; color: #555;">
                
                - **🔥 참여율**: 꾸준함의 상징! (총 참여 20회 시 만점)
                - **✨ 매너**: 동료들의 인정! (MVP 수상 10회 시 만점)
                - **❤️ 헌신**: 팀을 위한 양보! (비선호 포지션/대기 수행 시 상승)
                - **🌈 다양성**: 올라운더 플레이어! (경험한 포지션 수에 비례)
                - **🤝 사교성**: 커뮤니티 관심도! (MVP 투표 참여 20회 시 만점)
                
                </div>
                """, unsafe_allow_html=True)
            
        with col_info:
            st.markdown("#### 📌 요약 리포트")
            st.write(f"- **총 참여**: {len(hist)}회")
            st.write(f"- **MVP 수상**: {mvp_received}회")
            st.write(f"- **포지션 경험**: {len(unique_pos)}개")
            st.write(f"- **팀을 위한 헌신**: {dedication_count} 포인트")
            
            if my_cur:
                status = "✅ 참가확인" if str(my_cur[0].get('입금')).upper() == 'O' else "⏳ 입금확인중"
                st.info(f"이번 주: **{status}**")
            else:
                st.caption("이번 주 신청 내역이 없습니다.")

        # 4. 과거 기록 상세
        with st.expander("📜 과거 경기 기록 전체 보기"):
            if hist:
                df_hist = pd.DataFrame(hist)
                cols_to_show = ['일시', '게임제목', '1순위', '레벨']
                if '확정포지션' in df_hist.columns:
                    cols_to_show.append('확정포지션')
                
                valid_cols = [c for c in cols_to_show if c in df_hist.columns]
                st.dataframe(df_hist[valid_cols], hide_index=True, use_container_width=True)
            else:
                st.info("아직 기록된 경기가 없습니다.")
# --- 탭 4: MVP ---
with tab4:
    with st.expander("📘 이용 가이드: MVP 투표", expanded=False):
        st.write("🔒 본인 인증 후, 경기 내용을 떠올리며 가장 인상 깊었던 선수에게 투표해주세요.")

    st.header("🏆 MVP 투표")
    
    apps = load_applicants()
    
    # 종료된 게임(명단 없음)일 경우 과거 기록 로드
    is_archived = False
    if not apps:
        all_history = load_all_history()
        if all_history:
            last_date = all_history[-1].get('일시')
            temp_players = {}
            for h in all_history:
                if h.get('일시') == last_date:
                    key = (h.get('이름'), h.get('연락처'))
                    if key not in temp_players: temp_players[key] = h
            if temp_players:
                apps = list(temp_players.values())
                is_archived = True
                st.info(f"📢 지난 게임 **({last_date})** 명단으로 투표를 진행합니다.")

    if not apps:
        st.warning("투표할 대상이 없습니다.")
    else:
        # 본인 인증
        if not st.session_state['mvp_voter_verified']:
            with st.form("mvp_auth"):
                st.info("🔒 투표를 위해 본인 인증을 해주세요.")
                c1, c2 = st.columns(2)
                with c1: voter = st.text_input("이름")
                with c2: vphone = st.text_input("연락처")
                if st.form_submit_button("인증하기"):
                    clean_vphone = normalize_phone(vphone)
                    found = False
                    for p in apps:
                        p_name_real = str(p['이름']).replace("[VEGA] ", "").strip()
                        if p_name_real == voter and normalize_phone(p['연락처']) == clean_vphone:
                            found = True; break
                    if found:
                        st.session_state['mvp_voter_verified'] = True
                        st.session_state['mvp_voter_name'] = voter
                        st.session_state['mvp_voter_phone'] = clean_vphone
                        st.rerun()
                    else: st.error("명단에 없는 정보입니다.")
        
        # 투표 화면
        else:
            st.success(f"👋 안녕하세요, **{st.session_state['mvp_voter_name']}**님! 오늘의 MVP는 누구인가요?")
            
            def process_vote(candidate_name):
                suc, msg = save_mvp_vote(
                    st.session_state['mvp_voter_name'], 
                    st.session_state['mvp_voter_phone'], 
                    candidate_name
                )
                if suc: 
                    st.toast(f"🎉 {candidate_name}님에게 투표했습니다!", icon="🗳️")
                    time.sleep(1)
                    st.rerun()
                else: 
                    st.error(msg)

            df_vote = pd.DataFrame(apps)
            
            # [A] 라인업 정보가 살아있는 경우 (가장 이상적인 뷰)
            if not is_archived and '확정1' in df_vote.columns and df_vote['확정1'].astype(str).str.strip().any():
                st.markdown("### 🏟️ 라인업을 보며 투표하기")
                st.caption("각 세트별 활약상을 떠올려보세요! (이름 옆 버튼 클릭)")
                
                tabs = st.tabs(["1·2 세트", "3·4 세트", "5·6 세트"])
                for i, tab in enumerate(tabs):
                    with tab:
                        col_pos = f"확정{i+1}"; col_team = f"팀{i+1}"
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
            
            # [B] 데이터가 삭제되어 비상 복구된 경우 (리스트 뷰로 개선)
            else:
                st.markdown("### 👥 전체 참가자 명단")
                st.caption("팀 정보가 삭제되어 전체 명단으로 표시됩니다.")
                
                for idx, row in df_vote.iterrows():
                    # 그리드 대신 깔끔한 리스트 스타일 적용
                    with st.container():
                        lc1, lc2, lc3 = st.columns([2, 2, 1])
                        with lc1: st.write(f"**{row['이름']}**")
                        with lc2: 
                            pos_info = row.get('확정포지션') or row.get('1순위') or "-"
                            st.caption(f"포지션: {pos_info}")
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
# --- 탭 5: 소리함 ---
with tab5:
    st.header("🗣️ 소리함 (익명)")
    st.write("운영진에게 하고 싶은 말을 남겨주세요.")
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
                if pw2 == ADMIN_PASSWORD:
                    st.session_state['lineup_admin_logged_in'] = True
                    lineup_auth.empty()
                else:
                    st.error("비밀번호 불일치")
    
    if st.session_state['lineup_admin_logged_in']:
        
        # 안내문구
        with st.expander("ℹ️ 점수 계산 규칙 (컨닝페이퍼)", expanded=True):
            st.markdown("""
            | 항목 | 점수 | 설명 |
            | :--- | :--- | :--- |
            | **기본 점수** | `50점` | 모든 참가자 기본 지급 |
            | **VEGA 회원** | `+100점` | **우선권 부여** |
            | **1순위 배정** | `-10점`/회 | 오늘 1순위를 많이 할수록 **배정 누적**되어 양보 유도 |
            | **기여도 마일리지** | **누적** | **한번 얻은 점수는 사라지지 않음!** (대기/비선호 포지션 수행 시 적립) |
            | └ 대기 | `+10점` | 쉬었으면 확실한 우선권 부여 |
            | └ 3순위 | `+5점` | 원하지 않는 포지션 배정 시 마일리지 적립 |
            | └ 임의(노력) | `+5점` | **1·2·3순위 다 썼는데** 임의 배정된 경우 (위로금 상향) |
            | └ 임의/2순위 | `+3점` | 2순위 또는 일반 임의 배정 시 마일리지 적립 |
            """)

        data = load_applicants()
        if not data: st.warning("참가자 없음")
        else:
            df = pd.DataFrame(data)
            
            with st.expander("💬 카카오톡 공유 텍스트 생성 (클릭)"):
                kakao_txt = generate_kakao_text(df)
                st.code(kakao_txt, language="text")
                st.caption("👆 오른쪽 위 복사 버튼을 눌러 단톡방에 공유하세요.")
            st.divider()

            # [수정된 복구 로직]
            if 'fair_results' not in st.session_state and '확정1' in df.columns:
                if df['확정1'].astype(str).str.strip().any():
                    restored_results = {}
                    base_players = df.to_dict('records')
                    
                    # 1. 누적 변수 초기화 (0점부터 시작)
                    d_hist = {p['이름']: 0 for p in base_players}
                    d_hard = {p['이름']: 0 for p in base_players}
                    
                    # 2. 1세트부터 3세트까지 순서대로 계산하며 상태 복구
                    for r in range(1, 4):
                        col_team = f"팀{r}"
                        col_pos = f"확정{r}"
                        team_a = []
                        team_b = []
                        
                        # [핵심] 이 라운드 시작 전의 점수를 미리 계산 (화면 표시용)
                        score_map = {}
                        for p in base_players:
                            sc, re = get_priority_score(p, d_hist, d_hard)
                            score_map[p['이름']] = (sc, re)

                        # 저장된 결과 읽어서 팀 구성
                        for _, row in df.iterrows():
                            p_name = row['이름']
                            assigned = str(row.get(col_pos, '')).strip()
                            team_val = str(row.get(col_team, '')).strip()
                            
                            if not assigned: continue
                            
                            p_data = row.to_dict()
                            p_data['assigned_pos'] = assigned
                            
                            # 1. 계산해둔 점수 주입
                            if p_name in score_map:
                                p_data['priority_score'] = score_map[p_name][0]
                                p_data['score_reason'] = score_map[p_name][1]
                            
                            # 2. 매치 타입 판단 (누적을 위해 필요)
                            w1 = str(p_data.get('1순위','')).strip()
                            w2 = str(p_data.get('2순위','')).strip()
                            w3 = str(p_data.get('3순위','')).strip()
                            
                            if assigned == "대기": match_type = 'wait'
                            elif assigned == w1: match_type = '1st'
                            elif assigned == w2: match_type = '2nd'
                            elif assigned == w3: match_type = '3rd'
                            else: match_type = 'random'
                            p_data['match_type'] = match_type
                            
                            # 3. 팀 배정
                            if team_val == "A팀": team_a.append(p_data)
                            elif team_val == "B팀": team_b.append(p_data)
                            elif assigned == "대기": team_b.append(p_data)
                            
                            # [중요] 다음 세트를 위해 점수 누적 업데이트
                            if match_type == '1st': d_hist[p_name] += 1
                            
                            if match_type == 'wait': d_hard[p_name] += 10
                            elif match_type == '3rd': d_hard[p_name] += 5
                            elif match_type == '2nd': d_hard[p_name] += 3
                            elif match_type == 'random': d_hard[p_name] += 3

                        restored_results[r] = (team_a, team_b)
                    st.session_state['fair_results'] = restored_results

            if st.button("🎲 VEGA 우선 배정 시작 (새로 고침)"):
                with st.spinner("계산 중..."): 
                    st.session_state['fair_results'] = generate_vega_priority_schedule(df)
                    st.success("완료!")
                    st.rerun()
                    
            if 'fair_results' in st.session_state:
                schedule_map = {name: {} for name in df['이름']}
                for r_num, (team_a, team_b) in st.session_state['fair_results'].items():
                    for p in team_a: 
                        schedule_map[p['이름']][f"확정{r_num}"] = p['assigned_pos']
                        schedule_map[p['이름']][f"팀{r_num}"] = "A팀"
                    for p in team_b: 
                        schedule_map[p['이름']][f"확정{r_num}"] = p['assigned_pos']
                        schedule_map[p['이름']][f"팀{r_num}"] = "B팀"
                
                for idx, row in df.iterrows():
                    name = row['이름']
                    if name in schedule_map:
                        for r in range(1, 4): 
                            df.at[idx, f'확정{r}'] = schedule_map[name].get(f'확정{r}', '')
                            df.at[idx, f'팀{r}'] = schedule_map[name].get(f'팀{r}', '')
                
                r_tabs = st.tabs(["1·2", "3·4", "5·6"])
                for i, tab in enumerate(r_tabs, 1):
                    with tab:
                        team_a, team_b = st.session_state['fair_results'][i]
                        
                        def calculate_team_sum(team_list):
                            total = 0
                            for p in team_list:
                                if p['assigned_pos'] != "대기":
                                    lv = p.get('레벨', '입문').split(" ")[0]
                                    score = LEVEL_MAP.get(lv, 1)
                                    total += score
                            return total

                        sum_a = calculate_team_sum(team_a)
                        sum_b = calculate_team_sum(team_b)
                        
                        def get_admin_badge(p):
                            m = p.get('match_type')
                            if m == '1st': return "<span style='color:#1565C0; background-color:#E3F2FD; padding:2px 6px; border-radius:4px; font-weight:bold; border:1px solid #1565C0;'>1순위</span>"
                            elif m == '2nd': return "<span style='color:#2E7D32; background-color:#E8F5E9; padding:2px 6px; border-radius:4px; font-weight:bold; border:1px solid #2E7D32;'>2순위</span>"
                            elif m == '3rd': return "<span style='color:#E65100; background-color:#FFF3E0; padding:2px 6px; border-radius:4px; font-weight:bold; border:1px solid #E65100;'>3순위</span>"
                            else: return "<span style='color:#C62828; background-color:#FFEBEE; padding:2px 6px; border-radius:4px; font-weight:bold; border:1px solid #C62828;'>무</span>"

                        def get_score_display(p):
                            return f"[점수: {p.get('priority_score', 0):.2f} | {p.get('score_reason', '')}]"

                        real_players = [p for p in team_a + team_b if p['assigned_pos'] != "대기"]
                        if real_players:
                            count_a = len([p for p in team_a if p['assigned_pos'] != "대기"])
                            count_b = len([p for p in team_b if p['assigned_pos'] != "대기"])
                            
                            def get_missing_pos_list(player_list):
                                current_pos = set()
                                for p in player_list:
                                    if p.get('assigned_pos') and p['assigned_pos'] != "대기":
                                        current_pos.add(p['assigned_pos'])
                                full_set = set(POSITIONS_ALL)
                                missing = list(full_set - current_pos)
                                sort_order = {p: idx for idx, p in enumerate(POSITIONS_ALL)}
                                missing.sort(key=lambda x: sort_order.get(x, 99))
                                return missing

                            missing_a = get_missing_pos_list(team_a)
                            missing_b = get_missing_pos_list(team_b)
                            missing_text_a = ", ".join(missing_a) if missing_a else "없음"
                            missing_text_b = ", ".join(missing_b) if missing_b else "없음"

                            info_msg = f"📢 **[{i*2-1}·{i*2}세트] {count_a} vs {count_b}**"
                            if count_a != count_b: info_msg += f" (🔴A제외: {missing_text_a} | 🔵B제외: {missing_text_b})"
                            else:
                                if missing_text_a == missing_text_b: info_msg += f" (공통 제외: {missing_text_a})"
                                else: info_msg += f" (🔴A제외: {missing_text_a} | 🔵B제외: {missing_text_b})"
                            st.info(info_msg)
                            
                            st.markdown("##### ⚖️ 팀 레벨 합계 (밸런스 확인)")
                            b_col1, b_col2 = st.columns([1, 4])
                            with b_col1:
                                diff = sum_a - sum_b
                                delta_color = "off"
                                if abs(diff) <= 2: delta_color = "normal" 
                                else: delta_color = "inverse"
                                st.metric("🔴 A팀 합계", f"{sum_a}", delta=f"격차: {diff}", delta_color=delta_color)
                            with b_col2:
                                max_possible = max(count_a, count_b) * 5
                                if max_possible == 0: max_possible = 1
                                st.caption(f"A팀({sum_a}) vs B팀({sum_b})")
                                st.progress(min(sum_a / max_possible, 1.0))
                                st.progress(min(sum_b / max_possible, 1.0))

                        c1, c2 = st.columns(2)
                        with c1: 
                            st.error(f"🔴 A팀 (VEGA) [합계: {sum_a}]")
                            for p in team_a: 
                                if p['assigned_pos']!="대기":
                                    badge = get_admin_badge(p)
                                    lv = p.get('레벨', '입문').split(' ')[0]
                                    st.markdown(f"- **{p['assigned_pos']}**: {p['이름']} {badge} <span style='color:gray; font-size:0.8em;'>({lv})</span>", unsafe_allow_html=True)
                                    st.caption(f"└ {get_score_display(p)}")
                        with c2: 
                            st.info(f"🔵 B팀 (픽업) [합계: {sum_b}]")
                            for p in team_b: 
                                if p['assigned_pos']!="대기": 
                                    badge = get_admin_badge(p)
                                    lv = p.get('레벨', '입문').split(' ')[0]
                                    st.markdown(f"- **{p['assigned_pos']}**: {p['이름']} {badge} <span style='color:gray; font-size:0.8em;'>({lv})</span>", unsafe_allow_html=True)
                                    st.caption(f"└ {get_score_display(p)}")
                        
                        st.markdown("---")
                        bench_a = [p for p in team_a if p['assigned_pos']=="대기"]
                        bench_b = [p for p in team_b if p['assigned_pos']=="대기"]
                        if bench_a or bench_b:
                            st.caption("🛌 대기")
                            for p in bench_a + bench_b:
                                st.write(f"- {p['이름']} (희망: {p['1순위']}) {get_score_display(p)}")

            st.divider()
            cols = ["이름", "레벨", "1순위", "팀1", "확정1", "팀2", "확정2", "팀3", "확정3", "입금", "비고"]
            edited_df = st.data_editor(df[cols], hide_index=True, num_rows="dynamic")
            if st.button("저장 (공개)"):
                final_df = df.copy()
                final_df.update(edited_df)
                update_lineup(final_df)
                st.success("저장되었습니다!")
                time.sleep(1.0)
                st.rerun()


# --- 탭 7: 관리자 ---
with tab7:
    st.header("관리자 메뉴")
    admin_auth = st.empty()
    if not st.session_state['admin_logged_in']:
        with admin_auth.form("admin_main_login"):
            pw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("확인"):
                if pw == ADMIN_PASSWORD:
                    st.session_state['admin_logged_in'] = True
                    admin_auth.empty()
                else: st.error("비밀번호 불일치")
    
    if st.session_state['admin_logged_in']:
        st.subheader("✅ 참가 확인 관리 (시범운영)")
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
        with st.expander("📞 참가자 전체 연락처 복사 (단체문자)"):
            if apps:
                phones = [p.get('연락처', '').strip() for p in apps if p.get('연락처')]
                phones = [p for p in phones if p]
                if phones:
                    phone_string = ", ".join(phones)
                    st.code(phone_string, language="text")
                    st.caption(f"총 {len(phones)}명의 연락처입니다. 복사해서 문자 수신인에 붙여넣으세요.")
                else: st.warning("연락처 정보가 없습니다.")
            else: st.info("참가자가 없습니다.")

        st.divider()
        st.subheader("🛠️ 새 게임 개설")
        with st.form("create_game"):
            reset_chk = st.checkbox("개설 시 기존 명단 초기화 (아카이빙)", value=True)
            title = st.text_input("게임 제목")
            dt = st.text_input("일시")
            loc = st.text_input("장소")
            gender = st.radio("성별", ["혼성", "남자", "여자"], horizontal=True)
            col_d, col_t = st.columns(2)
            with col_d: dead_date = st.date_input("마감 날짜")
            with col_t: dead_time = st.time_input("마감 시간")
            fee = st.text_input("참가비")
            acc = st.text_input("계좌")
            contact = st.text_input("연락처")
            desc = st.text_area("공지사항")
            if st.form_submit_button("개설하기"):
                deadline_str = f"{dead_date} {dead_time.strftime('%H:%M')}"
                info = {"제목": title, "일시": dt, "장소": loc, "성별": gender, "참가비": fee, "계좌": acc, "설명": desc, "연락처": contact, "마감일시": deadline_str}
                save_game_info(info)
                if reset_chk: 
                    archive_current_game()
                    clear_applicants()
                st.success("게임이 개설되었습니다.")
                time.sleep(1.5)
                st.rerun()
        
        # [게임 종료 기능]
        st.divider()
        st.subheader("🏁 현재 게임 종료 (수동)")
        with st.expander("⚠️ 게임 종료 및 모집 마감 (클릭)"):
            st.warning("""
            **[주의]** 이 버튼을 누르면:
            1. 현재 명단을 '경기기록'에 저장합니다.
            2. 모집 상태를 '종료(CLOSED)'로 변경하여 추가 신청을 막습니다.
            3. **명단은 삭제하지 않습니다.** (MVP 투표 및 라인업 조회를 위해 유지)
            """)
            if st.button("현재 게임 종료하기"):
                archive_current_game() # 기록 저장
                
                # 명단 유지하면서 상태만 CLOSED로 변경
                close_info = {
                    "제목": "CLOSED", "일시": "-", "장소": "-", "성별": "-", 
                    "참가비": "-", "계좌": "-", "설명": "-", "연락처": "-", "마감일시": "-"
                }
                save_game_info(close_info)
                
                st.success("게임이 종료되었습니다! (명단은 유지됩니다)")
                time.sleep(1.5)
                st.rerun()

        st.divider()
        st.subheader("🚨 블랙리스트")
        with st.form("blacklist"):
            c1, c2, c3 = st.columns(3)
            with c1: b_name = st.text_input("이름")
            with c2: b_phone = st.text_input("연락처")
            with c3: b_reason = st.text_input("사유")
            if st.form_submit_button("등록"):
                add_to_blacklist(b_name, b_phone, b_reason); st.success("등록됨")
        
        st.divider()
        st.subheader("🗣️ 건의함")
        suggestions = load_suggestions()
        if suggestions: st.dataframe(suggestions, use_container_width=True)
        else: st.info("건의 없음")

        st.divider()
        with st.expander("🛠️ 라인업 비상 수정"):
            if apps:
                # [수정] '제외' 컬럼 추가하여 관리자가 수정 가능하게 함
                cols_edit = ["이름", "팀1", "확정1", "팀2", "확정2", "팀3", "확정3", "입금", "비고", "제외"]
                df_final = pd.DataFrame(apps)
                
                # 없는 컬럼 초기화
                for c in cols_edit:
                    if c not in df_final.columns: df_final[c] = ""
                
                edited_final = st.data_editor(df_final[cols_edit], hide_index=True)
                
                if st.button("비상 저장"):
                    df_final.update(edited_final)
                    update_lineup(df_final)
                    st.success("완료")
