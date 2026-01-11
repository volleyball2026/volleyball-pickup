import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import random
import copy
from datetime import datetime
import re
import time

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
    "2026.01.12": [
        "👥 인원수별(6~8인) 포지션 자동 조정 로직 적용",
        "ℹ️ 라인업 공개 시 경기 인원 및 제외 포지션 안내",
        "📢 노쇼(No-Show) 방지 및 필독 유의사항 추가",
        "📞 관리자용 참가자 연락처 일괄 복사 기능",
        "✅ '입금 확인' → '참가 확인'으로 용어 변경 (시범운영)",
        "🔄 관리자 저장 시 데이터 즉시 반영(새로고침) 적용"
    ],
    "2025.01.03": [
        "📊 포지션 경쟁률 표시 로직 수정 (6명=마감)",
        "📢 포지션 선택 주의사항 문구 추가",
        "📅 정식 출범 일정(월/수/금) 안내 추가",
        "🔄 게임 개설 시 명단 자동 새로고침 적용",
        "🤖 라인업 알고리즘 변경 (VEGA vs 픽업)"
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
            dst_sheet.append_row(['일시', '게임제목', '이름', '연락처', '1순위', '레벨'])
            
        if data:
            rows = []
            game_date = game_info.get('일시', datetime.now().strftime("%Y-%m-%d"))
            game_title = game_info.get('제목', 'Untitled')
            for p in data:
                rows.append([
                    game_date, game_title, 
                    p.get('이름', ''), p.get('연락처', ''), 
                    p.get('1순위', ''), p.get('레벨', '')
                ])
            for r in rows: dst_sheet.append_row(r)
        st.cache_data.clear()

@st.cache_data(ttl=5)
def load_applicants():
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet: return sheet.get_all_records()
    return []

def add_applicant(name, phone, level, pos1, pos2, pos3, note):
    sheet = get_sheet_instance(SHEET_APPLICANTS)
    if sheet:
        row_data = [
            name, normalize_phone(phone), level, pos1, pos2, pos3, 
            "", "", "", pos1, pos2, pos3, 
            anonymize_name(name), "X", note
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
            "이름(가림)", "입금", "비고"
        ]
        sheet.append_row(headers)
        
        if '이름(가림)' not in df.columns: df['이름(가림)'] = df['이름'].apply(anonymize_name)
        if '입금' not in df.columns: df['입금'] = 'X'
        if '비고' not in df.columns: df['비고'] = ''
            
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
            "이름(가림)", "입금", "비고"
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

# [수정] VEGA 절대 우대 + 인원수별 자동 조정 알고리즘
def assign_positions_in_team(team_members, history, wait_history):
    # 1. 우선순위 점수 계산
    for p in team_members:
        name = p['이름']
        played_1st = history.get(name, 0)
        waited = wait_history.get(name, 0)
        
        # [핵심 수정] VEGA 회원에게 압도적인 가산점 부여 (1000점)
        # 픽업 참가자가 아무리 점수가 높아도 VEGA를 이길 수 없음
        is_vega = "[VEGA]" in name
        vega_bonus = 1000 if is_vega else 0
        
        # 점수 = (VEGA 보너스) + (참가 적을수록 유리) + (대기 많을수록 유리) + (랜덤)
        p['priority_score'] = vega_bonus + (10 - played_1st) + (waited * 5) + random.random()
        p['assigned_pos'] = None 
    
    # 점수 높은 순 정렬 (VEGA 멤버들이 리스트 최상단으로 올라감)
    team_members.sort(key=lambda x: x['priority_score'], reverse=True)
    
    # 2. 팀 인원수에 따른 포지션 쿼터 조정 (6~8인제 대응)
    team_size = len(team_members)
    current_quotas = POSITION_QUOTAS.copy()
    
    if team_size == 8:
        cnt_fast = sum(1 for p in team_members if '속공' in p['1순위'])
        cnt_cb = sum(1 for p in team_members if '센터백' in p['1순위'])
        if cnt_fast >= cnt_cb: current_quotas['센터백'] = 0
        else: current_quotas['속공'] = 0
            
    elif team_size == 7:
        current_quotas['속공'] = 0
        current_quotas['센터백'] = 0
        
    elif team_size == 6:
        current_quotas['속공'] = 0
        current_quotas['센터백'] = 0
        current_quotas['백차'] = 0
    
    # 3. 포지션 배정 (1순위 -> 2순위 -> 3순위 -> 나머지)
    for p in team_members:
        pos1 = p['1순위']
        if current_quotas.get(pos1, 0) > 0:
            p['assigned_pos'] = pos1; current_quotas[pos1] -= 1; p['got_1st'] = True
        else: p['got_1st'] = False
            
    for p in team_members:
        if p['assigned_pos'] is None:
            pos2 = p['2순위']
            if pos2 and pos2 != "선택 안함" and current_quotas.get(pos2, 0) > 0:
                p['assigned_pos'] = pos2; current_quotas[pos2] -= 1
                
    for p in team_members:
        if p['assigned_pos'] is None:
            pos3 = p['3순위']
            if pos3 and pos3 != "선택 안함" and current_quotas.get(pos3, 0) > 0:
                p['assigned_pos'] = pos3; current_quotas[pos3] -= 1
                
    for p in team_members:
        if p['assigned_pos'] is None:
            allocated = False
            for pos, count in current_quotas.items():
                if count > 0:
                    p['assigned_pos'] = pos; current_quotas[pos] -= 1; allocated = True; break
            if not allocated: p['assigned_pos'] = "대기"
                
    return team_members

# [수정] 포지션 중복 방지 & 균형 분배가 강화된 팀 생성 알고리즘
def generate_vega_priority_schedule(df):
    players = df.to_dict('records')
    for p in players: p['score'] = calculate_score(p['레벨'])
    
    vegas = [p for p in players if "[VEGA]" in p['이름']]
    pickups = [p for p in players if "[VEGA]" not in p['이름']]
    
    history = {p['이름']: 0 for p in players}
    wait_history = {p['이름']: 0 for p in players}
    final_rounds = {}

    for round_num in range(1, 4):
        # 1. 매 라운드 섞기
        random.shuffle(vegas)
        random.shuffle(pickups)
        
        team_size = len(players) // 2
        
        # 2. 이번 경기의 '유효 포지션' 정의 (인원수에 따라 제외할 포지션 미리 계산)
        # 이 포지션에 해당하는 사람을 우선적으로 A팀 빈자리에 채워넣음
        valid_positions = set(POSITIONS_ALL)
        
        if team_size == 7:
            valid_positions -= {'속공', '센터백'}
        elif team_size == 6:
            valid_positions -= {'속공', '센터백', '백차'}
        elif team_size == 8:
            # 8인제는 전체 수요를 보고 결정해야 하지만, 팀 배정 단계에서는 
            # 일단 둘 다 유효하다고 보고, 나중에 배정 함수에서 쿼터로 조절하는 게 안전함.
            pass

        # 3. A팀 구성 시작 (VEGA 멤버 우선)
        team_a = vegas[:team_size]
        rem_vegas = vegas[team_size:] # 남는 VEGA는 B팀 후보
        
        # 4. A팀 빈자리 채우기 (스마트 스카우트 v2 - 한 명씩 체크)
        slots_needed = team_size - len(team_a)
        
        pool = pickups[:] # 픽업 멤버 풀
        selected_for_a = []
        
        # 현재 A팀(VEGA 멤버들)이 희망하는 1순위 포지션 목록
        current_positions = [p['1순위'] for p in team_a]
        
        for _ in range(slots_needed):
            # A팀에 아예 없는 '유효 포지션' 찾기
            missing_pos = list(valid_positions - set(current_positions))
            
            best_candidate = None
            
            # (1) A팀에 없는 포지션을 1순위로 원하는 사람 찾기
            candidates_perfect = [p for p in pool if p['1순위'] in missing_pos]
            
            if candidates_perfect:
                best_candidate = candidates_perfect[0] # 찾았다!
            else:
                # (2) 딱 맞는 사람이 없으면, 그냥 남은 사람 중 아무나 데려옴
                if pool:
                    best_candidate = pool[0]
            
            # 선발된 사람 이동
            if best_candidate:
                selected_for_a.append(best_candidate)
                current_positions.append(best_candidate['1순위']) # A팀 포지션 목록 갱신
                pool.remove(best_candidate) # 풀에서 제거
        
        # 최종 팀 구성
        team_a += selected_for_a
        team_b = rem_vegas + pool # 남은 VEGA + 남은 픽업

        # 5. 포지션 할당 (쿼터 적용)
        final_team_a = assign_positions_in_team(team_a, history, wait_history)
        final_team_b = assign_positions_in_team(team_b, history, wait_history)
        
        # 6. 기록 업데이트
        for p in final_team_a + final_team_b:
            name = p['이름']
            if p.get('got_1st', False): history[name] += 1
            if p['assigned_pos'] == "대기": wait_history[name] += 1
            
        final_rounds[round_num] = (final_team_a, final_team_b)
        
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
            for log in logs:
                st.write(f"- {log}")
    
    st.divider()
    
    # [수정] 문의하기 섹션 (링크 적용)
    st.markdown("### 📞 문의하기")
    # 아래 링크를 클릭하면 새 창으로 오픈채팅방이 열립니다.
    st.markdown("💬 [**오픈채팅방 입장 (클릭)**](https://open.kakao.com/o/gf1s6t9h)")
    # 소리함 탭 이동 기능은 Streamlit 미지원이므로 안내 문구로 대체
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
    st.header("즐겁게 배구하자! 월요배구회 🏐")
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
        - **지각 시**: 신청서의 **'도착 예정 시간'** 칸에 시간을 꼭 적어주세요.
    2. **경기 진행**: 12명 이상 모이면 경기를 진행합니다.
    3. **성별**: **남성 경기**이며, 남성 18명 미만 시 여성은 **수비 선수로만** 참가 가능합니다.
    4. **팀 배정**: 실력 균형을 맞춘 **자동 라인업 시스템**을 사용합니다. (편애 NO!)
    
    ---
    **💬 문의사항은 오픈채팅방을 이용해주세요.**
    [👉 여순광 배구 픽업 오픈채팅방 입장하기](https://open.kakao.com/o/gf1s6t9h)
    """)

# --- 탭 1: 참가 신청 ---
with tab1:
    if current_game:
        deadline_str = str(current_game.get('마감일시', '2099-12-31 23:59'))
        try: deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
        except: deadline_dt = datetime(2099, 12, 31, 23, 59)
        is_expired = datetime.now() > deadline_dt

        st.subheader(f"[{current_game['성별']}] {current_game['제목']}")
        c1, c2 = st.columns(2)
        with c1: st.write(f"**📅 일시:** {current_game['일시']}"); st.write(f"**📍 장소:** {current_game['장소']}")
        with c2: 
            st.write(f"**💰 참가비:** {current_game['참가비']}")
            if is_expired: st.error(f"**⏰ 마감:** {deadline_str} (종료)")
            else: st.info(f"**⏰ 마감:** {deadline_str} 까지")
        st.divider()

        if is_expired: st.warning("🚫 **참가 신청 기간이 지났습니다.**")
        else:
            st.write("### 👇 참가 신청서")
            with st.form("apply_form"):
                c1, c2 = st.columns(2)
                with c1: name = st.text_input("이름")
                with c2: phone = st.text_input("연락처", placeholder="01012345678")
                
                with st.expander("ℹ️ 레벨 기준 보기 (클릭)", expanded=False):
                    st.markdown("""
                    - **입문**: 기본기가 부족하여 실제 경기 참여는 어려움
                    - **초급**: 게임 경험은 적지만 참여 가능
                    - **중급**: 전국대회에 무리 없이 참여할 수 있는 수준
                    - **상급**: 전국대회 상위 무대에서도 원활히 활동 가능
                    - **최상급**: 전국대회 최상위권, 선출 준하는 실력
                    """)
                
                # VEGA 체크박스
                is_vega = st.checkbox("순천VEGA 회원 (우선권)")
                
                lc1, lc2 = st.columns([2, 1])
                with lc1: level = st.selectbox("참가자 레벨", LEVELS)
                with lc2: late_note = st.text_input("도착 예정 시간 (늦참 시)")
                
                st.markdown("---")
                
                # [수정] 포지션 선택 안내 문구 추가
                st.info("📢 **주의:** 1순위 마감 시 2·3순위가 없으면 **임의 배정**되거나 **대기**로 밀릴 수 있습니다. (2·3순위 필수 아님, 권장)")
                
                p1, p2, p3 = st.columns(3)
                with p1: pos1 = st.selectbox("1순위 (필수)", POSITIONS_ALL)
                with p2: pos2 = st.selectbox("2순위 (선택)", ["선택 안함"] + POSITIONS_ALL)
                with p3: pos3 = st.selectbox("3순위 (수비/속공)", ["선택 안함"] + POSITIONS_3RD)
                if st.form_submit_button("신청하기"):
                    if name and phone:
                        is_black, reason = check_blacklist(name, phone)
                        if is_black: st.error(f"🚨 신청 불가: 블랙리스트 ({reason})")
                        else:
                            final_name = f"[VEGA] {name}" if is_vega else name
                            add_applicant(final_name, phone, level, pos1, "" if pos2=="선택 안함" else pos2, "" if pos3=="선택 안함" else pos3, late_note)
                            st.success(f"{name}님 신청 완료!")
                    else: st.error("필수 입력 누락")
            
            with st.expander("🗑️ 신청 취소"):
                with st.form("cancel"):
                    cc1, cc2 = st.columns(2)
                    with cc1: c_name = st.text_input("이름")
                    with cc2: c_phone = st.text_input("연락처")
                    if st.form_submit_button("취소하기"):
                        suc, msg = cancel_applicant(c_name, c_phone)
                        if not suc:
                            suc, msg = cancel_applicant(f"[VEGA] {c_name}", c_phone)
                        
                        if suc: st.success(msg)
                        else: st.error(msg)

        st.divider()
        st.subheader("📊 실시간 참가 신청 현황")
        applicants = load_applicants()
        if applicants:
            df_public = pd.DataFrame(applicants)
            st.markdown("##### 🚦 포지션 경쟁률")
            if '1순위' in df_public.columns:
                counts = df_public['1순위'].value_counts()
                MAX_SLOTS = 6 
                cols = st.columns(4)
                for idx, (pos, count) in enumerate(counts.items()):
                    with cols[idx % 4]:
                        # [수정] 경쟁률 표시 로직
                        if count > MAX_SLOTS: 
                            st.metric(label=pos, value=f"{count}명", delta="초과!", delta_color="inverse")
                        elif count == MAX_SLOTS:
                            st.metric(label=pos, value=f"{count}명", delta="마감 임박", delta_color="off")
                        else: 
                            st.metric(label=pos, value=f"{count}명", delta="여유")
            
            st.divider()
            st.markdown("##### 📋 신청자 명단")
            if '입금' not in df_public.columns: df_public['입금'] = "X"
            # [수정] 입금완료 -> 참가확인
            df_public['상태'] = df_public['입금'].apply(lambda x: "✅ 참가확인" if str(x).strip().upper() == "O" else "-")
            
            if '이름' in df_public.columns: df_public['이름'] = df_public['이름'].apply(anonymize_name)
            if '레벨' in df_public.columns: df_public['레벨'] = df_public['레벨'].apply(simplify_level_name) 
            
            if '비고' not in df_public.columns: df_public['비고'] = ""
            
            show_cols = ["이름", "상태", "레벨", "1순위", "비고"]
            real_cols = [c for c in show_cols if c in df_public.columns]
            st.dataframe(df_public[real_cols], hide_index=True, use_container_width=True)
            # [추가] 노쇼 방지 안내 문구
            st.caption("📢 **유의사항:** 참가 확정 후 불참 시에는 꼭 **[신청 취소]**를 해주세요. \n"
                       "연락 없이 불참(No-Show)하는 경우가 반복되면, 원활한 운영을 위해 **향후 참가 신청이 제한**될 수 있습니다.")
        else: st.info("아직 신청자가 없습니다.")
    else: st.warning("모집 중인 게임이 없습니다.")

# --- 탭 2: 라인업 공개 ---
with tab2:
    with st.expander("📘 이용 가이드: 라인업 보는 법", expanded=False):
        st.markdown("""
        - **팀 확인**: A팀(🔴)과 B팀(🔵)으로 나뉩니다.
        - **포지션 아이콘**: ✅(1순위 배정), ⚠️(2/3순위 배정)
        """)

    st.header("📋 이번 주 라인업")
    data_final = load_applicants()
    if not data_final: st.info("확정 전")
    else:
        df_final = pd.DataFrame(data_final)
        st.divider()

        df_final['이름_masked'] = df_final['이름'].apply(anonymize_name)
        lineup_tabs = st.tabs(["1·2 세트", "3·4 세트", "5·6 세트"])
        for i, (col_team, col_pos) in enumerate([("팀1", "확정1"), ("팀2", "확정2"), ("팀3", "확정3")], 1):
            with lineup_tabs[i-1]:
                if col_pos in df_final.columns:
                    playing = df_final[df_final[col_pos] != '']
                    if not playing.empty:
                        # [추가] 경기 방식 및 제외 포지션 안내 기능
                        real_players = playing[playing[col_pos] != "대기"]
                        if not real_players.empty:
                            count_a = len(real_players[real_players[col_team]=="A팀"])
                            count_b = len(real_players[real_players[col_team]=="B팀"])
                            
                            # 현재 배정된 포지션 확인
                            assigned_set = set(real_players[col_pos].unique())
                            full_set = set(POSITIONS_ALL)
                            # 전체 포지션 중 배정되지 않은 포지션 찾기
                            missing = list(full_set - assigned_set)
                            
                            info_msg = f"📢 **[{i*2-1}·{i*2}세트] {count_a} vs {count_b} 경기**"
                            if missing:
                                info_msg += f" (제외 포지션: {', '.join(missing)})"
                            else:
                                info_msg += " (풀 포지션)"
                            
                            st.info(info_msg)

                        c1, c2 = st.columns(2)
                        with c1:
                            st.error("🔴 A팀 (VEGA)")
                            for _, r in playing[(playing[col_team]=="A팀") & (playing[col_pos]!="대기")].iterrows():
                                icon = "✅" if r[col_pos]==r['1순위'] else "⚠️"
                                st.write(f"- **{r[col_pos]}**: {r['이름_masked']} ({icon} {r['1순위']})")
                        with c2:
                            st.info("🔵 B팀 (픽업)")
                            for _, r in playing[(playing[col_team]=="B팀") & (playing[col_pos]!="대기")].iterrows():
                                icon = "✅" if r[col_pos]==r['1순위'] else "⚠️"
                                st.write(f"- **{r[col_pos]}**: {r['이름_masked']} ({icon} {r['1순위']})")
                        st.markdown("---")
                        bench = playing[playing[col_pos]=="대기"]
                        if not bench.empty:
                            st.caption(f"🛌 **대기 ({'다음 0순위' if i<3 else '수고하셨습니다'})**")
                            for _, r in bench.iterrows(): st.write(f"- {r['이름_masked']} (희망: {r['1순위']})")

# --- 탭 3: My Page ---
with tab3:
    with st.expander("📘 이용 가이드: 내 정보 확인", expanded=False):
        st.write("본인의 이름과 연락처를 입력하면 '입금 확인 여부'와 '과거 경기 기록'을 조회할 수 있습니다.")

    st.header("📊 My Page")
    with st.form("my_history"):
        c1, c2 = st.columns(2)
        with c1: my_name = st.text_input("이름")
        with c2: my_phone = st.text_input("연락처")
        if st.form_submit_button("조회"):
            if my_name and my_phone:
                clean_phone = normalize_phone(my_phone)
                cur_apps = load_applicants()
                
                # VEGA 태그 고려한 검색
                my_cur = [p for p in cur_apps if (p['이름']==my_name or p['이름']==f"[VEGA] {my_name}") and normalize_phone(p['연락처'])==clean_phone]
                
                st.subheader("📍 현재 신청 상태")
                if my_cur:
                    # [수정] 입금완료 -> 참가확인
                    status = "✅ 참가확인" if str(my_cur[0].get('입금')).upper() == 'O' else "미확인"
                    st.success(f"신청 확인됨! (상태: {status})")
                    st.dataframe(pd.DataFrame(my_cur)[['이름', '1순위', '레벨']], hide_index=True)
                else: st.warning("현재 신청 내역 없음")
                st.divider()
                
                hist = get_my_history(my_name, my_phone)
                st.subheader("📜 과거 기록")
                if hist:
                    df_hist = pd.DataFrame(hist)
                    req_cols = ['일시', '게임제목', '1순위', '레벨']
                    if set(req_cols).issubset(df_hist.columns):
                        st.dataframe(df_hist[req_cols], hide_index=True)
                    else:
                        st.dataframe(df_hist, hide_index=True)
                    st.success(f"총 {len(hist)}회 참가")
                else: 
                    st.info("기록 없음")

# --- 탭 4: MVP ---
with tab4:
    with st.expander("📘 이용 가이드: MVP 투표", expanded=False):
        st.write("🔒 개인정보 보호를 위해 참가자 본인 인증 후 투표 및 결과 확인이 가능합니다.")

    st.header("🏆 MVP 투표")
    apps = load_applicants()
    
    if not apps:
        st.warning("참가자 명단이 없어 투표할 수 없습니다.")
    else:
        auth_placeholder = st.empty()
        
        if not st.session_state['mvp_voter_verified']:
            with auth_placeholder.form("mvp_auth"):
                st.info("🔒 투표 및 결과 확인을 위해 본인 인증이 필요합니다.")
                voter = st.text_input("이름")
                vphone = st.text_input("연락처")
                if st.form_submit_button("확인"):
                    clean_vphone = normalize_phone(vphone)
                    found = False
                    for p in apps:
                        p_name_real = p['이름'].replace("[VEGA] ", "")
                        if p_name_real == voter and normalize_phone(p['연락처']) == clean_vphone:
                            found = True
                            break
                    
                    if found:
                        st.session_state['mvp_voter_verified'] = True
                        st.session_state['mvp_voter_name'] = voter
                        st.session_state['mvp_voter_phone'] = clean_vphone
                        auth_placeholder.empty()
                    else:
                        st.error("참가자 명단에 없는 정보입니다.")
            
            if not st.session_state['mvp_voter_verified']:
                st.divider()
                st.caption("🚫 **비참가자는 투표 현황 및 명예의 전당을 볼 수 없습니다.**")

        if st.session_state['mvp_voter_verified']:
            st.success(f"👋 환영합니다, {st.session_state['mvp_voter_name']}님!")
            
            df_mvp = pd.DataFrame(apps)
            candidate_list = df_mvp['이름'].tolist()
            
            with st.form("mvp_submit"):
                target_name = st.selectbox("🏅 MVP 선택 (실명 표시)", candidate_list)
                if st.form_submit_button("투표하기"):
                    suc, msg = save_mvp_vote(
                        st.session_state['mvp_voter_name'], 
                        st.session_state['mvp_voter_phone'], 
                        target_name
                    )
                    if suc: st.success(msg)
                    else: st.error(msg)
            
            if st.button("로그아웃"):
                st.session_state['mvp_voter_verified'] = False
                st.rerun()

            st.divider()
            st.subheader("📊 실시간 득표 현황 (Top 5)")
            rank = get_mvp_ranking_today()
            if not rank.empty: 
                st.dataframe(rank.head(5), hide_index=True, use_container_width=True)
            else: 
                st.info("아직 투표가 없습니다.")

            st.markdown("---")
            st.subheader("👑 명예의 전당")
            hof = get_mvp_hall_of_fame()
            if len(hof)>0: 
                hof['날짜'] = hof['일시']; hof['MVP'] = hof['MVP후보']
                st.dataframe(hof[['날짜', 'MVP', '득표수']], hide_index=True, use_container_width=True)

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
        data = load_applicants()
        if not data: st.warning("참가자 없음")
        else:
            df = pd.DataFrame(data)
            
            with st.expander("💬 카카오톡 공유 텍스트 생성 (클릭)"):
                kakao_txt = generate_kakao_text(df)
                st.code(kakao_txt, language="text")
                st.caption("👆 오른쪽 위 복사 버튼을 눌러 단톡방에 공유하세요.")
            st.divider()

            if st.button("🎲 VEGA 우선 배정 시작"):
                with st.spinner("계산 중..."): 
                    st.session_state['fair_results'] = generate_vega_priority_schedule(df)
                    st.success("완료!")
                    
            if 'fair_results' in st.session_state:
                # 데이터프레임에 반영 (저장 준비)
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
                
                # 화면 표시
                r_tabs = st.tabs(["1·2", "3·4", "5·6"])
                for i, tab in enumerate(r_tabs, 1):
                    with tab:
                        team_a, team_b = st.session_state['fair_results'][i]
                        
                        # [추가] 관리자용 경기 정보 (제외 포지션 확인)
                        real_players = [p for p in team_a + team_b if p['assigned_pos'] != "대기"]
                        if real_players:
                            count_a = len([p for p in team_a if p['assigned_pos'] != "대기"])
                            count_b = len([p for p in team_b if p['assigned_pos'] != "대기"])
                            
                            assigned_set = set(p['assigned_pos'] for p in real_players)
                            full_set = set(POSITIONS_ALL)
                            missing = list(full_set - assigned_set)
                            
                            info_msg = f"📢 **[{i*2-1}·{i*2}세트] {count_a} vs {count_b}**"
                            if missing: info_msg += f" (제외: {', '.join(missing)})"
                            else: info_msg += " (풀 포지션)"
                            st.info(info_msg)

                        c1, c2 = st.columns(2)
                        with c1: 
                            st.error("🔴 A팀 (VEGA)")
                            for p in team_a: 
                                if p['assigned_pos']!="대기":
                                    # 아이콘 로직 적용
                                    icon = "✅" if p['assigned_pos'] == p['1순위'] else "⚠️"
                                    st.write(f"- **{p['assigned_pos']}**: {p['이름']} ({icon} {p['1순위']})")
                        with c2: 
                            st.info("🔵 B팀 (픽업)")
                            for p in team_b: 
                                if p['assigned_pos']!="대기": 
                                    # 아이콘 로직 적용
                                    icon = "✅" if p['assigned_pos'] == p['1순위'] else "⚠️"
                                    st.write(f"- **{p['assigned_pos']}**: {p['이름']} ({icon} {p['1순위']})")
                        
                        # 대기 인원 표시
                        st.markdown("---")
                        bench_a = [p for p in team_a if p['assigned_pos']=="대기"]
                        bench_b = [p for p in team_b if p['assigned_pos']=="대기"]
                        if bench_a or bench_b:
                            st.caption("🛌 대기 (다음 우선권 부여)")
                            for p in bench_a + bench_b:
                                st.write(f"- {p['이름']} (희망: {p['1순위']})")

            st.divider()
            cols = ["이름", "레벨", "1순위", "팀1", "확정1", "팀2", "확정2", "팀3", "확정3", "입금", "비고"]
            edited_df = st.data_editor(df[cols], hide_index=True, num_rows="dynamic")
            if st.button("저장 (공개)"):
                final_df = df.copy(); final_df.update(edited_df); update_lineup(final_df); st.success("저장됨")
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
                else:
                    st.error("비밀번호 불일치")
    
    if st.session_state['admin_logged_in']:
        st.subheader("✅ 참가 확인 관리 (시범운영)")
        apps = load_applicants()
        if apps:
            df_manage = pd.DataFrame(apps)
            if '입금' not in df_manage.columns: df_manage['입금'] = 'X'
            
            df_manage['입금_bool'] = df_manage['입금'].apply(lambda x: True if str(x).upper() == 'O' else False)
            
            cols_manage = ["이름", "연락처", "입금_bool", "1순위"]
            edited_manage = st.data_editor(
                df_manage[cols_manage],
                column_config={"입금_bool": st.column_config.CheckboxColumn("참가 확인")},
                hide_index=True
            )
            
            # [수정] 저장 후 새로고침 (즉시 반영)
            if st.button("참가 현황 저장"):
                df_manage.update(edited_manage)
                df_manage['입금'] = df_manage['입금_bool'].apply(lambda x: 'O' if x else 'X')
                update_lineup(df_manage)
                st.success("저장되었습니다.")
                time.sleep(1.0) # 잠시 대기 후
                st.rerun()      # 새로고침!
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
        st.subheader("🛠️ 게임 개설")
        with st.form("create_game"):
            reset_chk = st.checkbox("명단 초기화 (아카이빙)", value=True)
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
                if reset_chk: archive_current_game(); clear_applicants()
                st.success("게임이 개설되었습니다.")
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
                cols_edit = ["이름", "팀1", "확정1", "팀2", "확정2", "팀3", "확정3", "입금", "비고"]
                df_final = pd.DataFrame(apps)
                # 에러 방지: 없는 컬럼 추가
                for c in cols_edit:
                    if c not in df_final.columns: df_final[c] = ""
                edited_final = st.data_editor(df_final[cols_edit], hide_index=True)
                if st.button("비상 저장"):
                    df_final.update(edited_final); update_lineup(df_final); st.success("완료")

st.markdown("---")
st.markdown("<div style='text-align: center; color: gray; font-size: small;'>Designed by <b>Heeseong</b></div>", unsafe_allow_html=True)
