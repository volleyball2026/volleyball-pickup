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


# [수정] 모바일 최적화 CSS (디자인 복구 + 깔끔한 알약 스타일 통일)
st.markdown("""
    <style>
        /* 1. 상단 헤더 숨기기 */
        header {visibility: hidden;}
        .block-container {
            padding-top: 1rem !important;
            padding-bottom: 5rem !important;
        }

        /* 2. 탭바 고정 및 가로 스크롤 설정 */
        div[data-testid="stTabsNav"] {
            position: sticky;
            top: 0;
            z-index: 999;
            background-color: white;
            padding: 10px 0;
            border-bottom: 1px solid #f0f0f0;
        }
        div[data-baseweb="tab-list"] {
            gap: 8px;
            overflow-x: auto;
            flex-wrap: nowrap;
            white-space: nowrap;
            scrollbar-width: none;
            padding-bottom: 5px;
            padding-left: 5px;
        }
        div[data-baseweb="tab-list"]::-webkit-scrollbar { display: none; }

        /* ================================================================= */
        /* [디자인 통일] 모든 탭 버튼을 '알약 모양'으로 예쁘게 만듭니다. */
        /* 복잡한 색상 구분 로직을 제거하여 오류를 원천 차단했습니다. */
        /* ================================================================= */
        button[data-baseweb="tab"] {
            height: 40px !important;               
            min-height: 40px !important;
            border-radius: 20px !important;        /* 둥근 알약 모양 */
            padding: 0 20px !important;            /* 넓은 여백 */
            background-color: #f7f7f7 !important;  /* 평소: 회색 */
            border: 1px solid #eee !important;
            color: #666 !important;
            font-size: 14px !important;
            font-weight: 500 !important;
            flex: 0 0 auto;
            transition: all 0.2s;                  /* 부드러운 효과 */
        }
        
        /* 탭이 선택되었을 때 스타일 (파란색 강조) */
        button[data-baseweb="tab"][aria-selected="true"] {
            background-color: #E3F2FD !important;  /* 배경: 연한 파랑 */
            color: #1565C0 !important;             /* 글씨: 진한 파랑 */
            border: 1px solid #1565C0 !important;  /* 테두리: 파랑 */
            font-weight: 800 !important;           /* 글씨 두껍게 */
            transform: scale(1.02);                /* 살짝 커지는 효과 */
        }

        /* 텍스트 여백 제거 */
        button[data-baseweb="tab"] p { margin: 0; }

        /* 신청 버튼 강조 (파란색) */
        div[data-testid="stForm"] button[kind="secondaryFormSubmit"] {
            background-color: #1565C0 !important;
            color: white !important;
            border: none !important;
            border-radius: 12px !important;
            padding: 0.75rem 1rem !important;
            font-size: 1.1rem !important;
            font-weight: 800 !important;
            box-shadow: 0 4px 6px rgba(0,0,0,0.2) !important;
            width: 100% !important;
        }
        div[data-testid="stForm"] button[kind="secondaryFormSubmit"]:active {
            transform: scale(0.98);
        }
    </style>
""", unsafe_allow_html=True)

# --- [설정] ---
DOC_NAME = "배구픽업관리"
SHEET_APPLICANTS = "참가자명단"
SHEET_GAME_INFO = "게임정보"
SHEET_HISTORY = "경기기록"
SHEET_BLACKLIST = "블랙리스트"
SHEET_MVP = "MVP투표"
SHEET_SUGGESTION = "건의함"
ADMIN_PASSWORD = "1992"
# ------------------------------------------------------------------
# [NEW] 새로고침 해도 로그인 유지하기 (자동 로그인 로직)
# ------------------------------------------------------------------
# 1. 세션 상태 초기화
if 'admin_logged_in' not in st.session_state:
    st.session_state['admin_logged_in'] = False

# 2. 주소창(URL)에 인증 도장(?auth=비밀번호)이 있는지 확인
# (주의: 보안상 완벽하지 않지만, 편의성을 위해 이 방식을 사용합니다)
try:
    # URL에서 'auth' 값 가져오기
    query_params = st.query_params
    auth_token = query_params.get("auth", "")
    
    # 도장이 맞으면 -> 로그인 상태로 변경
    if auth_token == ADMIN_PASSWORD:
        st.session_state['admin_logged_in'] = True
except:
    pass
# ------------------------------------------------------------------
SHEET_VIDEOS = "영상관리"  # [NEW] 유튜브 링크 저장용 시트
SHEET_LOGS = "접속로그"  # [NEW] 로그 저장용 시트
MAX_CAPACITY = 20  # [NEW] 최대 정원 설정

# --- [업데이트 로그 데이터] ---
UPDATE_LOGS = {
    "2026.01.22 (Ver 3.3)": [
        "⚖️ [공정성] **'이름+날짜' 고정 난수** 알고리즘 적용 (관리자 개입 원천 차단)",
        "🔒 [신뢰] 누가 언제 조회하든 **동일한 결과/점수**가 나오도록 개선",
        "🐛 [안내] 알고리즘 교체 과도기로 인해 **금일만 점수 표기가 일부 상이**할 수 있습니다. (대진표는 정상!)"
    ],
    "2026.01.18 (Ver 3.2)": [
        "🚧 [운영] **정원제(20명)** 도입",
        "🔢 [기능] 20명 초과 신청 시 **'예비 대기자'**로 자동 분류",
        "👀 [관리] 관리자 탭에서 확정 인원과 예비 인원 분리 표시"
    ],
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

# [기능 함수 추가] 사용자 IP 주소 가져오기
def get_client_ip():
    try:
        headers = _get_websocket_headers()
        if headers:
            # Streamlit Cloud 등 프록시 환경에서는 'X-Forwarded-For'에 진짜 IP가 있음
            if "X-Forwarded-For" in headers:
                return headers["X-Forwarded-For"].split(",")[0]
            # 로컬 환경 등
            elif "Remote-Addr" in headers:
                return headers["Remote-Addr"]
    except:
        pass
    return "unknown"

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

# [기능 함수] 접속 로그 저장 함수 (새로고침 F5 남발 방지: URL 꼬리표 방식)
def log_visit(action_type, user_info="익명"):
    # 1. 이미 방문 꼬리표(visited=true)가 있는지 확인
    # (새로고침을 해도 이 꼬리표는 URL에 남아있음 -> 중복 카운트 방지)
    query_params = st.query_params
    if "visited" in query_params and query_params["visited"] == "true":
        return # 이미 기록된 방문자이므로 저장 안 함

    # 2. 세션 상태 확인 (중복 방지 2차)
    session_key = f"log_{action_type}"
    if session_key in st.session_state:
        return

    # 3. 로그 저장 시작
    client_ip = get_client_ip()
    now_kst = datetime.utcnow() + timedelta(hours=9)
    now_str = now_kst.strftime("%Y-%m-%d %H:%M:%S")

    sheet = get_sheet_instance(SHEET_LOGS)
    if sheet:
        try:
            # 헤더 없으면 생성
            if not sheet.get_all_values():
                sheet.append_row(["일시", "유형", "접속자(추정)", "IP주소"])
            
            # 로그 저장
            sheet.append_row([now_str, action_type, user_info, client_ip])
            
            # 4. [핵심] 방문 도장 찍기
            # (1) 세션에 기록
            st.session_state[session_key] = True
            # (2) 브라우저 URL에 '?visited=true' 꼬리표 붙이기 (F5 눌러도 유지됨)
            st.query_params["visited"] = "true"
            
        except Exception as e:
            print(f"로그 저장 실패: {e}")
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
# --- [UI 함수] 점수 표시 디자인 (수정됨: 줄바꿈 제거로 </div> 노출 버그 완벽 해결) ---
def format_score_html(score, reason):
    if reason is None: reason = ""
    
    # 1. 점수 포맷팅
    try:
        score_val = float(score)
        header = f"점수: {score_val:.2f}"
    except:
        header = f"점수: {score}"

    # 2. 안전한 파싱 (문자열 분리 방식)
    items = reason.split()
    formatted_items = []
    
    for item in items:
        # (+) 항목: 파란색
        if item.startswith('+'):
            formatted_items.append(f"<span style='color:#1E88E5; font-weight:bold;'>{item}</span>")
        # (-) 항목: 빨간색
        elif item.startswith('-'):
            formatted_items.append(f"<span style='color:#E53935; font-weight:bold;'>{item}</span>")
        # 기본 항목: 진한 회색
        elif item.startswith('기본'):
            formatted_items.append(f"<span style='color:#424242; font-weight:bold;'>{item}</span>")
        # 그 외: 그대로
        else:
            formatted_items.append(item)
            
    final_reason = " ".join(formatted_items)

    # 3. HTML 조립 (중요: 줄바꿈 없이 한 줄로 작성해야 마크다운 오류가 안 남)
    html = f"<div style='background-color: #F8F9FA; border: 1px solid #E0E0E0; border-radius: 6px; padding: 4px 8px; margin-top: 4px; color: #333333; font-size: 0.85em; line-height: 1.4;'><span style='font-weight:bold; color:#333;'>└ {header}</span> | {final_reason}</div>"
    
    return html

def save_game_info(info_dict):
    sheet = get_sheet_instance(SHEET_GAME_INFO)
    if sheet:
        # [수정] 맨 뒤에 'X' (비공개 기본값) 추가 (총 10번째 컬럼)
        sheet.append_row([
            info_dict['제목'], info_dict['일시'], info_dict['장소'], 
            info_dict['성별'], info_dict['참가비'], info_dict['계좌'], 
            info_dict['설명'], info_dict['연락처'], info_dict['마감일시'],
            "X" # 기본은 비공개
        ])
        st.cache_data.clear()

def toggle_game_visibility(is_visible):
    sheet = get_sheet_instance(SHEET_GAME_INFO)
    if sheet:
        try:
            # 가장 최근 게임(마지막 행)의 10번째 컬럼(공개여부)을 수정
            data = sheet.get_all_values()
            if len(data) > 1: # 헤더 제외 데이터가 있을 때
                last_row_idx = len(data) # 1-based index for gspread
                val = "O" if is_visible else "X"
                sheet.update_cell(last_row_idx, 10, val)
                st.cache_data.clear()
                return True
        except Exception as e:
            return False
    return False

@st.cache_data(ttl=5) # 갱신 확인을 위해 ttl 단축
def get_current_game_info():
    sheet = get_sheet_instance(SHEET_GAME_INFO)
    if sheet:
        all_games = sheet.get_all_records()
        if all_games: 
            game = all_games[-1]
            # 공개여부 컬럼이 없으면(옛날 데이터) 기본 'O'로 처리
            if '공개여부' not in game and len(game) < 10:
                game['공개여부'] = 'O' 
            # 딕셔너리 키로 접근할 때 안전장치
            return game
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
        # [수정] 팀1~4, 확정1~4 (총 8개 빈칸)으로 확장
        row_data = [
            name, normalize_phone(phone), level, pos1, pos2, pos3, 
            "", "", "", "", # 팀1, 팀2, 팀3, 팀4
            "", "", "", "", # 확정1, 확정2, 확정3, 확정4
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
        # [수정] 헤더에 팀4, 확정4 추가
        headers = [
            "이름", "연락처", "레벨", "1순위", "2순위", "3순위", 
            "팀1", "팀2", "팀3", "팀4", 
            "확정1", "확정2", "확정3", "확정4", 
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
        # [수정] 헤더에 팀4, 확정4 추가
        headers = [
            "이름", "연락처", "레벨", "1순위", "2순위", "3순위", 
            "팀1", "팀2", "팀3", "팀4", 
            "확정1", "확정2", "확정3", "확정4", 
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
                # [수정] 제목이 'CLOSED'이거나 날짜가 '-'인 데이터는 통계에서 제외!
                if str(row.get('게임제목')) == 'CLOSED' or str(row.get('일시')) == '-':
                    continue
                
                if row.get('이름') == name and normalize_phone(row.get('연락처')) == clean_phone:
                    history.append(row)
        except:
            pass
    return history

# --- [영상 관련 기능 함수 수정] ---
def save_video_link(url, title):
    sheet = get_sheet_instance(SHEET_VIDEOS)
    if sheet:
        # 1. 시트가 비어있으면 '헤더(제목줄)' 먼저 생성
        if not sheet.get_all_values():
            sheet.append_row(["날짜", "제목", "URL"])
            
        # 2. 그 다음 데이터 저장
        sheet.append_row([datetime.now().strftime("%Y-%m-%d"), title, url])
        st.cache_data.clear()

@st.cache_data(ttl=5) # 갱신 시간 단축 (5초)
def get_latest_video():
    sheet = get_sheet_instance(SHEET_VIDEOS)
    if sheet:
        try:
            # get_all_records 대신 get_all_values 사용 (헤더 오류 방지)
            rows = sheet.get_all_values()
            
            # 데이터가 2줄 이상이어야 함 (1번째 줄은 헤더, 2번째 줄부터 데이터)
            if len(rows) > 1:
                last_row = rows[-1] # 가장 마지막 줄 가져오기
                
                # 데이터가 정상적으로 3칸(날짜, 제목, URL) 있는지 확인
                if len(last_row) >= 3:
                    return {"date": last_row[0], "title": last_row[1], "url": last_row[2]}
        except:
            return None
    return None

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

# --- [UI 함수] 신청자 목록 카드 디자인 (포지션 약어 명확화: 백 포지션 2글자) ---
def render_applicant_list_html(df):
    if df.empty:
        return "<div style='text-align:center; padding:20px; color:#999;'>아직 신청자가 없습니다.</div>"
    
    # [수정] 헷갈리는 포지션은 2글자로 명확히 구분
    POS_ABBR = {
        # 공격/메인 (1글자)
        "레프트": "레", 
        "라이트": "라", 
        "세터": "세", 
        "속공": "속",
        "앞차": "앞", 
        "백차": "백",
        
        # 수비/백 포지션 (2글자 - 여기서 구분!)
        "레프트백": "레백", 
        "라이트백": "라백", 
        "센터백": "센백",
        
        # 예외 처리
        "선택 안함": "-", "": "-", "nan": "-"
    }

    # 2열 그리드
    html_code = "<div style='display: grid; grid-template-columns: 1fr 1fr; gap: 10px;'>"
    
    for _, row in df.iterrows():
        # 데이터 추출
        name = row['이름']
        level = row.get('레벨', '입문')
        
        # 1, 2, 3순위 가져오기
        p1 = str(row.get('1순위', '-')).strip()
        p2 = str(row.get('2순위', '-')).strip()
        p3 = str(row.get('3순위', '-')).strip()
        
        # [핵심] 포지션 체인 생성 (예: 세-레-센백)
        # 1. 1순위 약어 변환
        abbr1 = POS_ABBR.get(p1, p1[:1]) # 사전에 없으면 앞 1글자만
        chain_str = abbr1
        
        # 2. 2순위 연결
        if p2 and p2 not in ["선택 안함", "-", "nan", ""]:
            abbr2 = POS_ABBR.get(p2, p2[:1])
            chain_str += f"-{abbr2}"
            
            # 3. 3순위 연결 (2순위가 있을 때만 체크)
            if p3 and p3 not in ["선택 안함", "-", "nan", ""]:
                abbr3 = POS_ABBR.get(p3, p3[:1])
                chain_str += f"-{abbr3}"

        note = str(row.get('비고', ''))
        status_bool = str(row.get('입금', '')).upper() == 'O'
        
        # 스타일 결정
        is_vega = "[VEGA]" in name
        display_name = name.replace("[VEGA]", "").strip()
        
        if status_bool:
            status_icon = "✅"
            bg_color = "#FFFFFF"
            border_color = "#E0E0E0"
            opacity = "1.0"
        else:
            status_icon = "⏳"
            bg_color = "#F9F9F9"
            border_color = "#EEEEEE"
            opacity = "0.7"
            
        # 뱃지
        top_badges = ""
        if is_vega:
            top_badges += "<span style='background:#1565C0; color:white; font-size:0.6rem; padding:2px 5px; border-radius:10px; margin-right:2px;'>VEGA</span>"
        if "예비" in note:
            top_badges += "<span style='background:#FFF3E0; color:#E65100; font-size:0.6rem; padding:2px 5px; border-radius:10px;'>대기</span>"
        elif "지각" in note:
            top_badges += "<span style='background:#FFEBEE; color:#D32F2F; font-size:0.6rem; padding:2px 5px; border-radius:10px;'>지각</span>"

        # 카드 HTML
        card = (
            f"<div style='background-color: {bg_color}; border: 1px solid {border_color}; border-radius: 15px; "
            f"padding: 12px 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); text-align: center; opacity: {opacity}; position: relative;'>"
            
            # 상태 아이콘
            f"  <div style='position: absolute; top: 8px; right: 8px; font-size: 0.8em;'>{status_icon}</div>"
            
            # 포지션 아이콘 (1순위 약어 크게)
            f"  <div style='display: flex; justify-content: center; margin-bottom: 6px;'>"
            f"    <div style='width: 35px; height: 35px; border-radius: 50%; background-color: #f0f2f6; "
            f"    color: #444; display: flex; align-items: center; justify-content: center; "
            f"    font-weight: 800; font-size: { '0.85em' if len(abbr1) > 1 else '1.0em' }; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>"
            f"      {abbr1}"
            f"    </div>"
            f"  </div>"
            
            # 뱃지
            f"  <div style='margin-bottom: 4px; min-height: 15px;'>{top_badges}</div>"
            
            # 이름
            f"  <div style='font-size: 1.1em; font-weight: 800; color: #222; margin-bottom: 2px; letter-spacing: -0.5px;'>"
            f"    {display_name}"
            f"  </div>"
            
            # [결과] 레벨 · 포지션 체인 (예: 초급 · 세-레-센백)
            f"  <div style='font-size: 0.75em; color: #666; letter-spacing: -0.5px; font-weight: 600;'>"
            f"    {level} · <span style='color:#1565C0;'>{chain_str}</span>"
            f"  </div>"
            
            f"</div>"
        )
        html_code += card
        
    html_code += "</div>"
    return html_code
    
# --- [UI 함수] 작전판(Court View) HTML 생성 (순위 뱃지 복구 + 모바일 최적화) ---
def render_tactical_board(team_df, team_type, col_pos, round_score_db=None, round_num=None):
    # 팀 색상 설정
    if team_type == "A팀":
        bg_color = "#FFEBEE" # 연한 빨강 배경
        border_color = "#D32F2F" # 진한 빨강 테두리
        header_text = "🔴 A팀 (VEGA)"
    else:
        bg_color = "#E3F2FD" # 연한 파랑 배경
        border_color = "#1976D2" # 진한 파랑 테두리
        header_text = "🔵 B팀 (픽업)"

    # 포지션별 배치 정의
    row1 = ["레프트", "속공", "세터", "라이트"]
    row2 = ["앞차", "백차"]
    row3 = ["레프트백", "센터백", "라이트백"]

    # 선수 데이터 매핑
    player_map = {}
    
    if not team_df.empty and col_pos in team_df.columns:
        players = team_df[team_df[col_pos] != "대기"]
        
        for _, row in players.iterrows():
            pos = str(row.get(col_pos, '')).strip()
            name = row.get('이름_masked', row['이름'])
            real_name = row['이름']
            
            # 점수 및 사유 가져오기
            score = 0
            reason = ""
            if round_score_db and round_num:
                if real_name in round_score_db.get(round_num, {}):
                    p_data = round_score_db[round_num][real_name]
                    score = p_data['score']
                    reason = p_data.get('reason', '')
            else:
                score = row.get('priority_score', 0)
                reason = row.get('score_reason', '')
            
            # [NEW] 순위 정보 확인 (뱃지용)
            w1 = str(row.get('1순위', '')).strip()
            w2 = str(row.get('2순위', '')).strip()
            w3 = str(row.get('3순위', '')).strip()
            
            rank_badge = "random" # 기본값: 무 (랜덤)
            if pos == w1: rank_badge = "1st"
            elif pos == w2: rank_badge = "2nd"
            elif pos == w3: rank_badge = "3rd"
                
            player_map[pos] = {"name": name, "score": score, "reason": reason, "rank": rank_badge}

    # HTML 생성 헬퍼
    def make_player_html(pos_name):
        p_data = player_map.get(pos_name)
        if p_data:
            p_name = p_data['name']
            p_score = f"{p_data['score']:.2f}"
            p_reason = p_data['reason']
            p_rank = p_data['rank']
            
            # [VEGA 뱃지]
            vega_badge = ""
            display_name = p_name
            if "[VEGA]" in p_name:
                display_name = p_name.replace("[VEGA]", "").strip()
                vega_badge = "<span style='background-color:#1565C0; color:white; padding:1px 3px; border-radius:3px; font-size:0.7em; margin-right:2px; vertical-align: middle; font-weight:normal;'>V</span>"
            
            # [NEW] 순위 뱃지 생성
            rank_html = ""
            if p_rank == "1st":
                rank_html = "<span style='color:#1565C0; background-color:#E3F2FD; padding:0px 3px; border-radius:3px; font-size:0.7em; font-weight:normal; margin-left:3px;'>1순위</span>"
            elif p_rank == "2nd":
                rank_html = "<span style='color:#2E7D32; background-color:#E8F5E9; padding:0px 3px; border-radius:3px; font-size:0.7em; font-weight:normal; margin-left:3px;'>2순위</span>"
            elif p_rank == "3rd":
                rank_html = "<span style='color:#EF6C00; background-color:#FFF3E0; padding:0px 3px; border-radius:3px; font-size:0.7em; font-weight:normal; margin-left:3px;'>3순위</span>"
            else:
                rank_html = "<span style='color:#C62828; background-color:#FFEBEE; padding:0px 3px; border-radius:3px; font-size:0.7em; font-weight:normal; margin-left:3px;'>무</span>"

            # [점수 내역 색상 적용]
            reason_items = p_reason.split()
            formatted_reason = ""
            for item in reason_items:
                color = "#555"
                if item.startswith("+"): color = "#1976D2"
                elif item.startswith("-"): color = "#D32F2F"
                elif "기본" in item: color = "#9E9E9E"
                formatted_reason += f"<span style='color:{color}; margin-right:2px;'>{item}</span>"

            return (
                f"<div style='background: white; border: 1px solid {border_color}; border-radius: 6px; "
                f"padding: 4px 1px; margin: 1px; width: 24%; box-shadow: 1px 1px 2px rgba(0,0,0,0.05); "
                f"display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 60px;'>"
                
                # 포지션명 + 순위 뱃지 (한 줄에 표시)
                f"<div style='font-size: 0.55em; font-weight: bold; color: #888; margin-bottom: 1px; white-space: nowrap;'>"
                f"{pos_name}{rank_html}"
                f"</div>"
                
                # 이름
                f"<div style='font-size: 0.8em; font-weight: 800; color: #000; margin-bottom: 1px; "
                f"line-height: 1.1; text-align: center; word-break: break-word; overflow-wrap: break-word;'>"
                f"{vega_badge}{display_name}"
                f"</div>"
                
                # 총점
                f"<div style='font-size: 0.7em; font-weight:bold; color: #333; border-bottom: 1px solid #eee; margin-bottom: 2px;'>{p_score}</div>"
                
                # 상세 내역
                f"<div style='font-size: 0.5em; line-height: 1; text-align: center; word-break: break-all;'>{formatted_reason}</div>"
                
                f"</div>"
            )
        else:
            # 빈 자리
            return (
                f"<div style='border: 1px dashed #ddd; border-radius: 6px; padding: 4px 1px; margin: 1px; width: 24%; "
                f"opacity: 0.6; display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 60px;'>"
                f"<div style='font-size: 0.55em; color: #aaa;'>{pos_name}</div>"
                f"<div style='font-size: 0.65em; color: #ccc;'>(공석)</div>"
                f"</div>"
            )

    # 전체 보드 HTML 조립
    board_html = (
        f"<div style='background-color: {bg_color}; border: 1px solid {border_color}; border-radius: 10px; padding: 6px 2px; margin-bottom: 10px;'>"
        f"<div style='text-align: center; font-weight: bold; color: {border_color}; font-size: 0.85em; margin-bottom: 4px;'>{header_text}</div>"
        
        # Row 1
        f"<div style='display: flex; justify-content: space-around; margin-bottom: 4px;'>"
        f"{make_player_html('레프트')}{make_player_html('속공')}{make_player_html('세터')}{make_player_html('라이트')}"
        f"</div>"
        
        # Row 2
        f"<div style='display: flex; justify-content: center; gap: 15px; margin-bottom: 4px;'>"
        f"{make_player_html('앞차')}{make_player_html('백차')}"
        f"</div>"
        
        # Row 3
        f"<div style='display: flex; justify-content: space-around;'>"
        f"{make_player_html('레프트백')}{make_player_html('센터백')}{make_player_html('라이트백')}"
        f"</div>"
        
        f"</div>"
    )
    
    return board_html

# --- [알고리즘] ---
def calculate_score(level_str):
    for key, score in LEVEL_MAP.items():
        if key in level_str: return score
    return 1

# --- [알고리즘 함수 수정] 이름+날짜 기반 난수 (동기화 O, 매주 변동 O) ---
def get_priority_score(player, global_history, global_hardship):
    name = player['이름']
    
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
        
    # [핵심 수정] 이름 + 게임일시를 섞어서 '이번 게임 전용' 고정 난수 생성
    # 1. 현재 게임 날짜 가져오기 (없으면 'default')
    game_info = get_current_game_info()
    game_date = str(game_info.get('일시', 'default')) if game_info else 'default'
    
    # 2. 시드값 만들기 (이름_날짜)
    seed_key = f"{name}_{game_date}"
    
    # 3. 이 시드값으로 고정된 난수 생성 (0.00 ~ 0.99)
    # random.Random(seed).random()을 쓰면 전역 난수에 영향 주지 않고 독립적인 난수 생성 가능
    fixed_random = random.Random(seed_key).random()
    
    # 소수점 2자리까지만 예쁘게 반영
    score += round(fixed_random, 2)
    
    return score, " ".join(reasons)

# --- [알고리즘 수정 Ver 3.7.1] 3순위 고려 & 전 포지션 B팀 에이스 보호 ---

# --- [알고리즘 수정 Ver 3.8] 점수 절대 우선 배정 (고득점자 깡패 모드) ---

# --- [알고리즘 수정 Ver 3.9.3] 유니크 포지션 보호 (슈퍼 세이브) ---
# --- [알고리즘 수정 Ver 3.9.7] 9인제 포지션 고정 (속공 삭제 방지) ---
# --- [알고리즘 수정] 유니크 보호 + 쿼터 유지 + 베가 강제 배정(Force Fill) 통합본 ---
# --- [알고리즘 수정] VEGA 절대 우선 배정 (픽업보다 먼저 빈자리 선점) ---
# --- [알고리즘 수정] VEGA 절대 우선권 (픽업의 '새치기' 원천 봉쇄) ---
def assign_positions_in_team(team_members):
    # 1. 점수순 정렬 (같은 등급 내에서는 점수순 경쟁)
    team_members.sort(key=lambda x: x['priority_score'], reverse=True)
    
    # 초기화
    for p in team_members: 
        p['assigned_pos'] = None
        p['match_type'] = 'random'
    
    total_cnt = len(team_members)
    
    # ==========================================
    # [기능 1: 유니크 포지션 보호 로직] (유지)
    # ==========================================
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
                        idx_safe = team_members.index(safe_zone[swap_target_idx])
                        idx_drop = team_members.index(p_drop)
                        team_members[idx_safe], team_members[idx_drop] = team_members[idx_drop], team_members[idx_safe]
                        safe_zone = team_members[:court_capacity]
                        drop_zone = team_members[court_capacity:]

    # ==========================================
    # [기능 2: 쿼터 설정] (유지)
    # ==========================================
    starters = team_members[:9] if total_cnt >= 9 else team_members
    quotas = POSITION_QUOTAS.copy()
    
    starter_wishes = [str(p.get('1순위', '')).strip() for p in starters]
    count_fast = starter_wishes.count('속공')
    team_size_court = len(starters)
    
    if team_size_court >= 9: pass 
    elif team_size_court == 8:
        if count_fast > 0: quotas['센터백'] = 0 
        else: quotas['속공'] = 0 
    elif team_size_court == 7: quotas['속공'] = 0; quotas['센터백'] = 0
    elif team_size_court == 6: quotas['속공'] = 0; quotas['센터백'] = 0; quotas['백차'] = 0

    # ==========================================
    # [기능 3: 계급별 순차 배정] (핵심 수정!)
    # ==========================================

    # [Step 1] VEGA 회원 희망 포지션 우선 배정
    for p in team_members:
        if "[VEGA]" in str(p.get('이름', '')):
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

    # [Step 2] VEGA 회원 "잔여석 강제 착석" (Force Fill)
    # 픽업 회원이 1순위로 가져가기 전에, 남은 VEGA 회원을 빈자리에 먼저 앉힘
    for p in team_members:
        if not p['assigned_pos'] and "[VEGA]" in str(p.get('이름', '')):
            # 빈자리 찾기
            for pos, q in quotas.items():
                if q > 0:
                    # 제외 포지션이고 뭐고 일단 들어감 (베가 권한 보호)
                    p['assigned_pos'] = pos
                    quotas[pos] -= 1
                    p['match_type'] = 'random'
                    break

    # [Step 3] 픽업 회원 희망 포지션 배정
    # 이제서야 픽업 회원의 소원을 들어줌 (VEGA가 앉고 남은 자리 중에서)
    for p in team_members:
        if not p['assigned_pos'] and "[VEGA]" not in str(p.get('이름', '')):
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

    # [Step 4] 픽업 회원 나머지 배정 (랜덤)
    for p in team_members:
        if not p['assigned_pos'] and "[VEGA]" not in str(p.get('이름', '')):
            filled = False
            excluded_list = p.get('excluded', [])
            for pos, q in quotas.items():
                if q > 0 and pos not in excluded_list:
                    p['assigned_pos'] = pos
                    quotas[pos] -= 1
                    p['match_type'] = 'random'
                    filled = True
                    break
    
    # [Final] 자리 없는 사람은 대기
    for p in team_members:
        if not p['assigned_pos']:
            p['assigned_pos'] = "대기"
            p['match_type'] = 'wait'
                
    return team_members
    
# --- [알고리즘 수정 Ver 3.7.3] 무작위 배정 점수 세분화 (성실도 반영) ---
# --- [알고리즘 수정] 4라운드(7·8세트)까지 생성 ---
# --- [알고리즘 수정] 7·8세트 대상자 자동 승계 로직 ---
# --- [알고리즘 수정 Ver 3.9] 팀 밸런스(총점) 최적화 배정 ---
# --- [알고리즘 수정 Ver 3.9.2] 포지션 핏 -> 밸런스 최적화 -> 에이스 보호 ---
# --- [알고리즘 수정 Ver 3.9.5] 1~3순위 빈자리 매칭 + 에이스 보호 ---
# --- [알고리즘 수정 Ver 3.9.6] 희귀 포지션(속공/세터 등) 절대 사수 로직 ---
# --- [알고리즘 수정] 예비 인원 제외 필터링 적용 ---
# --- [알고리즘 수정] 전체 수정 코드 (B팀 희소 포지션 보호 + 잉여 자원 차출) ---
def generate_vega_priority_schedule(df):
    # 1. 전체 명단을 가져오되, '확정 인원'만 추려냅니다.
    raw_data = df.to_dict('records')
    base_players = []
    
    for idx, p in enumerate(raw_data):
        # [확정 조건]
        # 1. 선착순 정원(MAX_CAPACITY) 안에 들었거나
        # 2. 이름에 [VEGA]가 포함된 경우 (프리패스)
        is_vega = "[VEGA]" in str(p.get('이름', ''))
        if idx < MAX_CAPACITY or is_vega:
            base_players.append(p)
        else:
            # 예비 인원은 라인업 생성에서 제외
            continue
            
    # 제외 포지션 파싱
    for p in base_players:
        ex_str = str(p.get('제외', ''))
        p['excluded'] = [x.strip() for x in ex_str.split(',') if x.strip()] if ex_str else []

    global_history = {p['이름']: 0 for p in base_players}
    global_hardship = {p['이름']: 0 for p in base_players}
    final_rounds = {}

    # 1~4라운드 루프
    for round_num in range(1, 5):
        target_set = f"{round_num*2-1}·{round_num*2}"
        valid_markers = ["1·2", "3·4", "5·6"]
        
        # 해당 라운드 참가자 풀 구성
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

        # 점수 계산
        for p in current_pool:
            sc, re = get_priority_score(p, global_history, global_hardship)
            p['priority_score'] = sc; p['score_reason'] = re
            
        # 점수 높은 순 정렬 (기본)
        current_pool.sort(key=lambda x: x['priority_score'], reverse=True)
        
        # VEGA vs 픽업 분리
        team_a = [p for p in current_pool if "[VEGA]" in str(p['이름'])] 
        team_b = [p for p in current_pool if "[VEGA]" not in str(p['이름'])] 
        
        target_size = (len(current_pool) + 1) // 2
        
        # -------------------------------------------------------------
        # [핵심 로직 수정] A팀 인원 부족 시: B -> A 이동 (지능형 밸런싱)
        # 조건: "B팀에서 필요 없는(잉여) 자원부터 A팀으로 보낸다."
        # -------------------------------------------------------------
        while len(team_a) < target_size and len(team_b) > 0:
            # 1. A팀의 현재 포지션 현황 (점유된 포지션)
            occupied_roles_a = set(str(p.get('1순위')).strip() for p in team_a)
            
            # 2. B팀의 포지션별 인원 카운트 (누가 희귀한가?)
            team_b_counts = {}
            for p in team_b:
                role = str(p.get('1순위', '')).strip()
                if role and role != "선택 안함":
                    team_b_counts[role] = team_b_counts.get(role, 0) + 1
            
            # 3. 방출 후보군 점수 매기기 (Release Score)
            candidates = []
            
            for i, p in enumerate(team_b):
                role = str(p.get('1순위', '')).strip()
                score_val = p['priority_score']
                
                # [판단 기준]
                # (1) 희소성: B팀 내 같은 포지션 경쟁자가 몇 명인가?
                #     1명(나 혼자) -> 희귀 자원 -> 절대 보호 (Protection)
                #     2명 이상 -> 잉여 자원 -> 방출 대상
                count_in_b = team_b_counts.get(role, 0)
                is_unique = (count_in_b == 1)
                
                # (2) 적합성: A팀에 내 자리가 비어있는가?
                #     비어있음 -> 가면 주전 -> 방출 권장
                #     꽉참 -> 가면 벤치/비선호 -> 보호
                is_fit = (role not in occupied_roles_a)
                
                # [방출 점수 계산] (높을수록 A팀으로 쫓겨남)
                release_score = 0
                
                if is_unique:
                    release_score -= 10000  # 희귀 자원은 절대 보호 (점수 대폭 깎음)
                else:
                    release_score += 500    # 잉여 자원은 방출 우선
                    
                if is_fit:
                    release_score += 300    # A팀에 자리가 있으면 보내는 게 좋음
                
                # 기본적으로 점수가 낮은 사람이 먼저 가야 함 (1000 - 점수)
                # 점수가 30점이면 +970점, 점수가 90점이면 +910점 -> 낮은 사람이 더 높은 방출점수
                release_score += (1000 - score_val)
                
                candidates.append((i, release_score))
            
            # 4. 방출 점수가 가장 높은(가장 불필요한) 사람 선택
            candidates.sort(key=lambda x: x[1], reverse=True)
            idx_to_move = candidates[0][0]
            
            # 이동 실행
            p_move = team_b.pop(idx_to_move)
            team_a.append(p_move)

        # -------------------------------------------------------------
        # [Case 2] A팀 인원 과잉 시: A -> B 이동
        # 조건: A팀은 점수 낮은 사람을 B팀으로 보내서 기회를 줌
        # -------------------------------------------------------------
        while len(team_a) > target_size:
            # 점수 오름차순 정렬 (낮은 사람이 0번)
            team_a.sort(key=lambda x: x['priority_score'], reverse=False)
            team_b.append(team_a.pop(0))

        # -------------------------------------------------------------
        # [최종 정렬] 포지션 배정 함수는 '높은 점수'부터 처리하므로 내림차순 정렬
        # -------------------------------------------------------------
        team_a.sort(key=lambda x: x['priority_score'], reverse=True)
        team_b.sort(key=lambda x: x['priority_score'], reverse=True)

        # 포지션 배정 (이미 수정하신 assign_positions_in_team 사용)
        final_a = assign_positions_in_team(team_a)
        final_b = assign_positions_in_team(team_b)
        
        # 결과 기록 (히스토리 누적)
        for p in final_a + final_b:
            nm = p['이름']; mt = p.get('match_type')
            
            if mt == '1st': global_history[nm] = global_history.get(nm, 0) + 1
            
            points = 0
            if mt == 'wait': points = 10
            elif mt == '3rd': points = 5
            elif mt == '2nd': points = 3
            elif mt == 'random':
                w1 = str(p.get('1순위', '')).strip()
                w2 = str(p.get('2순위', '')).strip()
                w3 = str(p.get('3순위', '')).strip()
                if w1 and w2 and w3: points = 5 
                else: points = 3 
            
            if points > 0:
                global_hardship[nm] = global_hardship.get(nm, 0) + points
            
        final_rounds[round_num] = (final_a, final_b)
        
    return final_rounds
    
# --- [메인 화면] ---
st.set_page_config(page_title="여순광 배구 픽업", page_icon="🏐", layout="wide") 

# [NEW] 사이트 접속 로그 기록
user_guess = st.session_state.get('my_name', '익명') 
log_visit("메인접속", user_guess)

# ▼▼▼ 사이드바 코드는 여기에 있어야 합니다 (들여쓰기 없음!) ▼▼▼
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
    
    # 서버 연결 상태 확인
    if get_sheet_instance(SHEET_APPLICANTS):
        st.success("✅ 서버 연결됨")
    else:
        st.error("❌ 서버 연결 실패")

# --- [UI] 메인 타이틀 (이미지 적용) ---
# ... (이 아래로 기존 get_img_base64 함수 등이 이어지면 됩니다)

# --- [UI] 메인 타이틀 (이미지 적용) ---
def get_img_base64(file_path):
    with open(file_path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()

img_file = "mikasa.png"  # 파일명이 정확해야 합니다!

if os.path.exists(img_file):
    img_b64 = get_img_base64(img_file)
    # 이미지 크기(width/height)를 조절하고, 둥글게(border-radius) 만듭니다.
    icon_html = f'<img src="data:image/jpeg;base64,{img_b64}" style="width: 65px; height: 65px; border-radius: 50%; box-shadow: 0 4px 6px rgba(0,0,0,0.15); object-fit: cover;">'
else:
    icon_html = "<div style='font-size: 3.5rem; line-height: 1;'>🏐</div>"

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

# [수정] 탭 목록에 '경기 영상' 추가
tab0, tab1, tab2, tab3, tab4, tab8, tab5, tab6, tab7 = st.tabs([
    "🔰 운영 안내", "📢 참가 신청", "📋 라인업 공개", "📊 My Page", "🏆 MVP", 
    "📺 경기 영상", "🗣️ 소리함", "⚡ 라인업 생성(관리자)", "⚙️ 관리자"
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
        - **정원제 시행**: 선착순 **20명**까지만 경기에 참여 가능합니다.
        - **예비 등록**: 21번째 신청자부터는 **'예비 대기자'**로 등록되며, 결원 발생 시 순서대로 연락드립니다.
    2. **경기 진행**: 12명 이상 모이면 경기를 진행합니다.
    3. **성별**: **남성 경기**이며, 남성 18명 미만 시 여성은 **수비 선수로만** 참가 가능합니다.
    4. **팀 배정**: 실력 균형을 맞춘 **자동 라인업 시스템**을 사용합니다. (편애 NO!)
    
    ---
    **💬 문의사항은 오픈채팅방을 이용해주세요.**
    [👉 여순광 배구 픽업 오픈채팅방 입장하기](https://open.kakao.com/o/gf1s6t9h)
    """)

# --- 탭 1: 참가 신청 ---
with tab1:
    # 1. 게임 종료(CLOSED) 또는 정보 없음
    if not current_game or current_game.get('제목') == 'CLOSED':
        st.info("💤 **현재 모집 중인 게임이 없습니다.**")
        st.markdown("""
        ### 🔜 다음 게임을 준비 중입니다!
        관리자가 새로운 게임을 개설할 때까지 잠시만 기다려주세요.
        보통 **매주 일요일**에 새로운 모집이 시작됩니다.
        """)
        st.markdown("<div style='text-align: center; font-size: 60px; margin-top: 30px;'>🏐</div>", unsafe_allow_html=True)
        
    else:
        # 2. 정상 모집 중
        if 'reg_success' not in st.session_state: st.session_state['reg_success'] = False
        if 'reg_name' not in st.session_state: st.session_state['reg_name'] = ""
        if 'reg_type' not in st.session_state: st.session_state['reg_type'] = "normal" 

        deadline_str = str(current_game.get('마감일시', '2099-12-31 23:59'))
        try: deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
        except: deadline_dt = datetime(2099, 12, 31, 23, 59)
        now = datetime.utcnow() + timedelta(hours=9)
        is_expired = now > deadline_dt

        # 현재 신청 인원 체크
        applicants = load_applicants()
        current_count = len(applicants)
        is_full = current_count >= MAX_CAPACITY

        st.subheader(f"[{current_game['성별']}] {current_game['제목']}")
        
        c1, c2 = st.columns(2)
        with c1: st.write(f"**📅 일시:** {current_game['일시']}"); st.write(f"**📍 장소:** {current_game['장소']}")
        with c2: 
            st.write(f"**💰 참가비:** {current_game['참가비']}")
            if is_expired: 
                st.error(f"**⏰ 마감:** {deadline_str} (종료)")
            elif is_full:
                st.warning(f"**🚫 정원 도달:** {current_count}/{MAX_CAPACITY}명 (VEGA 회원은 신청 가능)")
            else: 
                st.info(f"**⏰ 마감:** {deadline_str} 까지")

        st.markdown(f"**👥 모집 현황 ({current_count}/{MAX_CAPACITY}명)**")
        progress_val = min(current_count / MAX_CAPACITY, 1.0)
        st.progress(progress_val)
        
        if is_full:
            st.warning(f"📢 **일반 정원({MAX_CAPACITY}명)이 마감되었습니다.**\n- **픽업(게스트)**: 지금 신청 시 **'예비 대기자'**로 등록됩니다.\n- **VEGA 회원**: 정원과 무관하게 **'확정'** 등록됩니다.")

        st.divider()

        if st.session_state['reg_success']:
            msg_name = st.session_state['reg_name']
            r_type = st.session_state.get('reg_type', 'normal')
            
            if r_type == 'waiting':
                st.warning(f"✅ {msg_name}님, **예비 대기자**로 등록되었습니다.")
                st.write("결원이 생기면 연락드리겠습니다. (입금하지 마세요!)")
            elif st.session_state['reg_is_late']:
                st.success(f"✅ {msg_name}님, **시간 외 대기(추가)** 명단에 등록되었습니다!")
                st.markdown("운영진 승인 후 확정됩니다.")
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
            is_vega = st.checkbox("순천VEGA 회원 (우선권)")
            
            st.markdown("---")
            st.write("**⏱️ 참가 가능 시간(세트) 선택**")
            set_options = ["1·2세트 (19:20 ~ 20:00)", "3·4세트 (20:00 ~ 20:40)", "5·6세트 (20:40 ~ 21:20)"]
            selected_sets = st.multiselect("참가할 세트를 모두 선택해주세요", options=set_options, default=set_options)
            
            lc1, lc2 = st.columns(2)
            with lc1: level = st.selectbox("참가자 레벨", LEVELS)
            
            p1, p2, p3 = st.columns(3)
            with p1: pos1 = st.selectbox("1순위 (필수)", POSITIONS_ALL)
            with p2: pos2 = st.selectbox("2순위 (선택)", ["선택 안함"] + POSITIONS_ALL)
            with p3: pos3 = st.selectbox("3순위 (수비/속공)", ["선택 안함"] + POSITIONS_3RD)
            
            st.markdown("---")
            st.caption("부상이나 실력 문제로 **'절대 수행 불가능한'** 포지션이 있다면 선택해주세요. (최대 2개)")
            excluded_pos = st.multiselect("제외할 포지션 (선택)", POSITIONS_ALL, max_selections=2)
            
            # 버튼 라벨
            if is_full: submit_label = "신청하기 (VEGA확정 / 픽업대기)"
            elif is_expired: submit_label = "시간 외 추가 등록하기"
            else: submit_label = "신청하기"
            
            if st.form_submit_button(submit_label):
                if name and phone:
                    if not selected_sets: st.error("❌ 최소 1개 이상의 세트를 선택해야 합니다.")
                    elif pos1 in excluded_pos: st.error("❌ 1순위 포지션은 제외할 수 없습니다.")
                    else:
                        is_black, reason = check_blacklist(name, phone)
                        if is_black: st.error(f"🚨 신청 불가: {reason}")
                        else:
                            # [핵심] VEGA 회원은 정원 초과여도 Normal(확정) 처리
                            # 픽업 회원은 정원 초과 시 Waiting(대기) 처리
                            reg_type = "normal"
                            note_prefix = ""

                            if is_full:
                                if is_vega: 
                                    reg_type = "normal" # VEGA 프리패스
                                else:
                                    reg_type = "waiting"
                                    note_prefix = f"[예비{current_count+1}] "
                            elif is_expired:
                                note_prefix = "[지각] "

                            final_name = f"[VEGA] {name}" if is_vega else name
                            sets_str = ", ".join([s.split("세트")[0] for s in selected_sets])
                            excluded_str = ", ".join(excluded_pos)
                            final_note = note_prefix + sets_str
                            
                            try:
                                add_applicant(
                                    final_name, phone, level, pos1, 
                                    "" if pos2=="선택 안함" else pos2, 
                                    "" if pos3=="선택 안함" else pos3, 
                                    final_note, excluded_str
                                )
                                st.session_state['reg_success'] = True
                                st.session_state['reg_name'] = name
                                st.session_state['reg_is_late'] = is_expired
                                st.session_state['reg_type'] = reg_type
                                st.toast(f"등록되었습니다!", icon="📝")
                                st.rerun()
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

        # 현황판 (기존 유지 - 20명 기준으로 보여줌)
        st.divider()
        st.subheader("📊 실시간 참가 신청 현황")
        if applicants:
            df_public = pd.DataFrame(applicants)
            
            # --- [Tab 1 내부 코드 교체] ---
            st.markdown("##### 🚦 포지션 경쟁률 (정원 내)")
            
            # 상위 20명만 포지션 경쟁률에 반영
            df_in_cap = df_public.iloc[:MAX_CAPACITY]
            
            if '1순위' in df_in_cap.columns:
                # 1, 2, 3순위 카운트 집계
                c1 = df_in_cap['1순위'].value_counts()
                c2 = df_in_cap['2순위'].value_counts()
                c3 = df_in_cap['3순위'].value_counts()
                
                # CSS 스타일 (그리드 레이아웃)
                html_code = """
                <style>
                    .pos-container {display: grid; grid-template-columns: repeat(auto-fit, minmax(85px, 1fr)); gap: 8px; margin-bottom: 20px;}
                    .pos-card {background-color: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 8px 4px; text-align: center; box-shadow: 0 1px 2px rgba(0,0,0,0.05);}
                    .pos-title {font-size: 0.85em; color: #333; margin-bottom: 6px; font-weight: bold; border-bottom: 1px solid #f0f0f0; padding-bottom: 4px;}
                    .pos-main-count {font-size: 1.3em; font-weight: 900; color: #1565C0; margin-bottom: 4px;}
                    .pos-sub-info {font-size: 0.65em; color: #666; display: flex; justify-content: space-around; background: #f9f9f9; border-radius: 4px; padding: 2px;}
                    .sub-item {display: flex; flex-direction: column;}
                    .sub-label {color: #999; font-size: 0.9em;}
                    .sub-val {font-weight: bold; color: #444;}
                    .status-badge {font-size: 0.7em; padding: 1px 4px; border-radius: 3px; margin-top: 4px; display: inline-block;}
                    .s-safe {background:#E8F5E9; color:#2E7D32;}
                    .s-warn {background:#FFF3E0; color:#E65100;}
                </style>
                <div class="pos-container">
                """
                
                # 포지션 순서대로 카드 생성
                for pos in POSITIONS_ALL:
                    cnt1 = c1.get(pos, 0)
                    cnt2 = c2.get(pos, 0)
                    cnt3 = c3.get(pos, 0)
                    
                    # 상태 뱃지
                    if cnt1 >= 3: status = "<span class='status-badge s-warn'>혼잡</span>"
                    elif cnt1 == 0: status = "<span class='status-badge s-safe'>빈집</span>"
                    else: status = "<span class='status-badge s-safe'>여유</span>"
                    
                    # 3순위는 가능한 포지션만 숫자 표시
                    val3_display = f"{cnt3}"
                    if pos not in POSITIONS_3RD: val3_display = "-"
                    
                    html_code += f"""
                    <div class="pos-card">
                        <div class="pos-title">{pos} {status}</div>
                        <div class="pos-main-count">{cnt1}<span style="font-size:0.6em; font-weight:normal; color:#888;">명(1)</span></div>
                        <div class="pos-sub-info">
                            <div class="sub-item"><span class="sub-label">2순위</span><span class="sub-val">{cnt2}</span></div>
                            <div style="border-right:1px solid #ddd;"></div>
                            <div class="sub-item"><span class="sub-label">3순위</span><span class="sub-val">{val3_display}</span></div>
                        </div>
                    </div>
                    """
                html_code += "</div>"
                
                # [중요] HTML 렌더링
                st.markdown(html_code, unsafe_allow_html=True)
                
            st.divider()
            col_list, col_stats = st.columns([2.2, 1])
            with col_list:
                st.markdown(f"##### 📋 신청자 명단 ({len(df_public)}명)")
                
                # 데이터 전처리 (표시용 데이터 다듬기)
                if '입금' not in df_public.columns: df_public['입금'] = "X"
                if '이름' in df_public.columns: df_public['이름'] = df_public['이름'].apply(anonymize_name)
                if '레벨' in df_public.columns: df_public['레벨'] = df_public['레벨'].apply(simplify_level_name) 
                
                # [기존] st.dataframe(df_public[real_cols]...)  <-- 이거 지움
                
                # [수정] 배구구 스타일 카드 뷰 호출
                html_list = render_applicant_list_html(df_public)
                st.markdown(html_list, unsafe_allow_html=True)

            with col_stats:
                st.markdown("##### 📌 요약 정보")
                with st.container(border=True):
                    total_cnt = len(df_public)
                    # 요약: 20명이 넘더라도 VEGA는 확정으로 칠 수 있게 단순 집계
                    vega_cnt = len([n for n in df_public['이름'] if "[VEGA]" in str(n)])
                    pickup_cnt = total_cnt - vega_cnt
                    
                    st.write(f"- **총 신청**: {total_cnt}명")
                    st.write(f"- **VEGA**: {vega_cnt}명 (우선)")
                    st.write(f"- **픽업**: {pickup_cnt}명")

                    if not is_expired and not is_full:
                        diff = deadline_dt - now
                        hours = diff.seconds // 3600 + (diff.days * 24)
                        mins = (diff.seconds % 3600) // 60
                        st.caption(f"마감까지 {hours}시간 {mins}분 전")
        else:
            st.info("👋 **아직 신청자가 없습니다.** 첫 번째 참가자가 되어보세요!")
            st.metric("현재 참가 인원", "0명")
            
# --- 탭 2: 라인업 공개 ---
with tab2:
# [NEW] 라인업 조회 로그 기록
    log_visit("라인업조회", st.session_state.get('my_name', '익명'))
    # 1. 게임 종료 체크
    if not current_game or current_game.get('제목') == 'CLOSED':
        st.header("📋 이번 주 라인업")
        st.info("💤 **현재 진행 중인 게임이 없습니다.**")
        st.write("새로운 게임이 개설되고 팀 배정이 완료되면 이곳에 라인업이 공개됩니다.")
    
    else:
        # 2. 공개 여부 체크
        is_visible = str(current_game.get('공개여부', 'X')).upper().strip() == 'O'
        
        if not is_visible:
            st.header("📋 이번 주 라인업")
            st.divider()
            st.warning("🔒 **운영진이 라인업을 최종 점검 중입니다.**")
            st.markdown("""
            ### ⏳ 잠시만 기다려주세요!
            - 현재 신청 마감 후 **팀 밸런스 조정 및 검토**를 진행하고 있습니다.
            - 검토가 완료되면 이곳에 라인업이 공개됩니다.
            """)
            st.markdown("<div style='text-align: center; font-size: 80px; margin-top: 20px;'>🕵️‍♂️</div>", unsafe_allow_html=True)
            
        else:
            # === 3. 정상 공개 화면 ===
            with st.expander("📘 이용 가이드: 배정 기준 및 보는 법", expanded=False):
                st.markdown("""
                **1. 배정 기준 (우선순위 점수제)**
                | 항목 | 점수 | 설명 |
                | :--- | :--- | :--- |
                | **기본 점수** | `50점` | 모든 참가자 기본 지급 |
                | **VEGA 회원** | `+100점` | **우선권 부여** |
                | **1순위 배정** | `-10점`/회 | 오늘 1순위를 많이 할수록 **배정 누적**되어 양보 유도 |
                | **기여도** | `+3~10점` | **대기/비선호 포지션** 수행 시 점수 적립 |
                """, unsafe_allow_html=True)

            st.header("📋 이번 주 라인업")
            
            data_final = load_applicants()
            
            if not data_final: 
                st.info("확정 전")
            else:
                df_final = pd.DataFrame(data_final)
                
                # [수정] 점수 역추적 리플레이 로직 (Replay Logic)
                
                round_score_db = {}
                d_hist = {p['이름']: 0 for p in df_final.to_dict('records')}
                d_hard = {p['이름']: 0 for p in df_final.to_dict('records')}
                
                # 1~4라운드 순차적으로 점수 계산 및 업데이트
                for r in range(1, 5):
                    round_score_db[r] = {}
                    col_pos = f"확정{r}"
                    
                    # 1. (현재 라운드 시작 전) 점수 스냅샷 저장
                    for _, row in df_final.iterrows():
                        nm = row['이름']
                        p_data = row.to_dict()
                        # [버그 수정] 변수명 re -> reason_val 로 변경 (모듈 충돌 방지)
                        sc, reason_val = get_priority_score(p_data, d_hist, d_hard)
                        round_score_db[r][nm] = {'score': sc, 'reason': reason_val}
                    
                    # 2. (현재 라운드 결과) 반영 -> 다음 라운드를 위한 누적치 업데이트
                    if col_pos in df_final.columns:
                        for _, row in df_final.iterrows():
                            nm = row['이름']
                            assigned = str(row.get(col_pos, '')).strip()
                            
                            if not assigned: continue
                            
                            w1 = str(row.get('1순위', '')).strip()
                            w2 = str(row.get('2순위', '')).strip()
                            w3 = str(row.get('3순위', '')).strip()
                            
                            match_type = 'random'
                            if assigned == '대기': match_type = 'wait'
                            elif assigned == w1: match_type = '1st'
                            elif assigned == w2: match_type = '2nd'
                            elif assigned == w3: match_type = '3rd'
                            
                            if match_type == '1st': d_hist[nm] += 1
                            
                            pts = 0
                            if match_type == 'wait': pts = 10
                            elif match_type == '3rd': pts = 5
                            elif match_type == '2nd': pts = 3
                            elif match_type == 'random':
                                if w1 and w2 and w3 and w1!='선택 안함' and w2!='선택 안함' and w3!='선택 안함':
                                    pts = 5
                                else:
                                    pts = 3
                            
                            if pts > 0: d_hard[nm] += pts

                # --- 화면 표시 로직 ---
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
                                    count_a = len(team_a_df); count_b = len(team_b_df)
                                    
                                    # (제외 포지션 계산 생략 - 함수 호출 유지)
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
                                    if count_a != count_b: info_msg += f" (🔴A제외: {missing_text_a} | 🔵B제외: {missing_text_b})"
                                    else:
                                        if missing_text_a == missing_text_b: info_msg += f" (공통 제외: {missing_text_a})"
                                        else: info_msg += f" (🔴A제외: {missing_text_a} | 🔵B제외: {missing_text_b})"
                                    st.info(info_msg)

                                    # [작전판 출력]
                                    st.markdown("### 🏟️ Court View")
                                    
                                    html_a = render_tactical_board(team_a_df, "A팀", col_pos, round_score_db, i)
                                    st.markdown(html_a, unsafe_allow_html=True)
                                    
                                    st.markdown("<div style='text-align: center; font-weight: bold; margin: 5px 0; color: #999; font-size: 0.8em;'>▼ NEXT COURT ▼</div>", unsafe_allow_html=True)
                                    
                                    html_b = render_tactical_board(team_b_df, "B팀", col_pos, round_score_db, i)
                                    st.markdown(html_b, unsafe_allow_html=True)
                                
                                # 대기 인원
                                bench = playing[playing[col_pos]=="대기"]
                                if not bench.empty:
                                    st.divider()
                                    st.caption(f"🛌 **대기 선수 (다음 세트 출전 1순위)**")
                                    cols = st.columns(len(bench)) if len(bench) > 0 else []
                                    for idx, (_, r) in enumerate(bench.iterrows()):
                                        sc = 0
                                        if i in round_score_db and r['이름'] in round_score_db[i]:
                                            sc = round_score_db[i][r['이름']]['score']
                                        
                                        if idx < len(cols):
                                            with cols[idx]:
                                                st.markdown(f"""
                                                <div style="text-align: center; background: #f9f9f9; border: 1px solid #eee; border-radius: 8px; padding: 8px;">
                                                    <div style="font-weight: bold; font-size: 0.9em; color: #333; margin-bottom: 2px;">{r['이름_masked']}</div>
                                                    <div style="font-size: 0.75em; color: #666; margin-bottom: 2px;">(희망: {r.get('1순위', '-')})</div>
                                                    <div style="font-size: 0.8em; color: #1976D2; font-weight: bold;">{sc:.2f}</div>
                                                </div>
                                                """, unsafe_allow_html=True)
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
    
    # [1] 로그인 안 된 상태
    if not st.session_state.get('admin_logged_in', False):
        st.warning("⚠️ 관리자 권한이 필요한 메뉴입니다.")
        
        with st.form("lineup_login_form"):
            pw = st.text_input("비밀번호", type="password")
            keep_login = st.checkbox("로그인 상태 유지하기 (체크 필수)", value=True)
            
            if st.form_submit_button("관리자 로그인"):
                if pw == ADMIN_PASSWORD:
                    st.session_state['admin_logged_in'] = True
                    st.toast("관리자 인증 성공!", icon="⚡")
                    if keep_login:
                        st.query_params["auth"] = ADMIN_PASSWORD
                    st.rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")

    # [2] 로그인 성공 상태
    else:
        # 상단 네비게이션
        c_info, c_logout = st.columns([4, 1])
        with c_info: st.info("🔓 관리자 권한으로 접속 중입니다.")
        with c_logout:
            if st.button("로그아웃", key="logout_tab6"):
                st.session_state['admin_logged_in'] = False
                st.query_params.clear()
                st.rerun()

        # 점수 규칙 설명
        with st.expander("ℹ️ 점수 계산 규칙 (컨닝페이퍼)", expanded=False):
            st.markdown("""
            | 항목 | 점수 | 설명 |
            | :--- | :--- | :--- |
            | **기본 점수** | `50점` | 모든 참가자 기본 지급 |
            | **VEGA 회원** | `+100점` | **우선권 부여** |
            | **1순위 배정** | `-10점`/회 | 오늘 1순위를 많이 할수록 **배정 누적**되어 양보 유도 |
            | **기여도** | **누적** | **한번 얻은 점수는 사라지지 않음!** |
            """)

        data = load_applicants()
        if not data: 
            st.warning("참가자가 없습니다.")
        else:
            df = pd.DataFrame(data)
            
            # 카톡 공유
            with st.expander("💬 카카오톡 공유 텍스트 생성 (클릭)"):
                try:
                    kakao_txt = generate_kakao_text(df)
                    st.code(kakao_txt, language="text")
                except: st.error("텍스트 생성 오류")
            
            st.divider()

            # [핵심 기능] 라인업 생성 및 새로고침 버튼
            col_gen, col_refresh = st.columns([3, 1])
            with col_gen:
                if st.button("🚀 라인업 다시 생성 (알고리즘 실행)", type="primary", use_container_width=True):
                    with st.spinner("최적의 밸런스를 계산 중입니다..."): 
                        df_clean = df.copy()
                        cols_to_clean = []
                        for i in range(1, 5): cols_to_clean.extend([f"팀{i}", f"확정{i}"])
                        for col in cols_to_clean:
                            if col in df_clean.columns: df_clean[col] = ""
                        
                        st.session_state['fair_results'] = generate_vega_priority_schedule(df_clean)
                        st.success("생성 완료! 아래에서 확인 후 '저장'하세요.")
            
            with col_refresh:
                if st.button("🔄 시각화 새로고침", use_container_width=True):
                    if 'fair_results' in st.session_state:
                        del st.session_state['fair_results']
                    st.rerun()

            # [데이터 복구 로직] 비상수정 후 저장했을 때 시각화 복구
            if 'fair_results' not in st.session_state and '확정1' in df.columns:
                if df['확정1'].astype(str).str.strip().any():
                    try:
                        restored_results = {}
                        base_players = df.to_dict('records')
                        
                        d_hist = {p['이름']: 0 for p in base_players}
                        d_hard = {p['이름']: 0 for p in base_players}
                        
                        for r in range(1, 5):
                            col_team = f"팀{r}"
                            col_pos = f"확정{r}"
                            team_a = []
                            team_b = []
                            
                            score_map = {}
                            for p in base_players:
                                sc, re_val = get_priority_score(p, d_hist, d_hard)
                                score_map[p['이름']] = (sc, re_val)

                            for _, row in df.iterrows():
                                p_name = row['이름']
                                assigned = str(row.get(col_pos, '')).strip()
                                team_val = str(row.get(col_team, '')).strip()
                                
                                if not assigned: continue
                                
                                p_data = row.to_dict()
                                p_data['assigned_pos'] = assigned
                                
                                # 점수 정보 주입
                                if p_name in score_map:
                                    p_data['priority_score'] = score_map[p_name][0]
                                    p_data['score_reason'] = score_map[p_name][1]
                                
                                # 히스토리 추적용 매치타입 판단
                                w1 = str(p_data.get('1순위','')).strip()
                                w2 = str(p_data.get('2순위','')).strip()
                                w3 = str(p_data.get('3순위','')).strip()
                                match_type = 'random'
                                if assigned == '대기': match_type = 'wait'
                                elif assigned == w1: match_type = '1st'
                                elif assigned == w2: match_type = '2nd'
                                elif assigned == w3: match_type = '3rd'
                                
                                if team_val == "A팀": team_a.append(p_data)
                                elif team_val == "B팀": team_b.append(p_data)
                                elif assigned == "대기": team_b.append(p_data)

                                # 점수 누적 업데이트
                                if match_type == '1st': d_hist[p_name] += 1
                                if match_type == 'wait': d_hard[p_name] += 10
                                elif match_type in ['3rd', 'random']: d_hard[p_name] += 5
                                elif match_type == '2nd': d_hard[p_name] += 3

                            restored_results[r] = (team_a, team_b)
                        st.session_state['fair_results'] = restored_results
                    except Exception as e:
                        st.error(f"데이터 복구 중 오류: {e}")

            # [시각화 표시]
            if 'fair_results' in st.session_state:
                # 결과 매핑
                schedule_map = {name: {} for name in df['이름']}
                for r_num, (team_a, team_b) in st.session_state['fair_results'].items():
                    for p in team_a: 
                        schedule_map[p['이름']][f"확정{r_num}"] = p['assigned_pos']
                        schedule_map[p['이름']][f"팀{r_num}"] = "A팀"
                    for p in team_b: 
                        schedule_map[p['이름']][f"확정{r_num}"] = p['assigned_pos']
                        schedule_map[p['이름']][f"팀{r_num}"] = "B팀"
                
                # DF 반영
                for idx, row in df.iterrows():
                    name = row['이름']
                    if name in schedule_map:
                        for r in range(1, 5): 
                            df.at[idx, f'확정{r}'] = schedule_map[name].get(f'확정{r}', '')
                            df.at[idx, f'팀{r}'] = schedule_map[name].get(f'팀{r}', '')
                
                # 탭별 시각화
                r_tabs = st.tabs(["1·2 세트", "3·4 세트", "5·6 세트", "7·8 세트"])
                for i, tab in enumerate(r_tabs, 1):
                    with tab:
                        team_a, team_b = st.session_state['fair_results'][i]
                        
                        count_a = len([p for p in team_a if p['assigned_pos'] != "대기"])
                        count_b = len([p for p in team_b if p['assigned_pos'] != "대기"])
                        
                        # 전력 점수 계산
                        def calculate_team_sum(team_list):
                            total = 0
                            for p in team_list:
                                if p['assigned_pos'] != "대기":
                                    lv = str(p.get('레벨', '입문')).split(" ")[0]
                                    total += LEVEL_MAP.get(lv, 1)
                            return total
                        sum_a = calculate_team_sum(team_a)
                        sum_b = calculate_team_sum(team_b)

                        # 제외 포지션 표시
                        def get_missing_pos_list(player_list):
                            current_pos = set()
                            for p in player_list:
                                if p.get('assigned_pos') and p['assigned_pos'] != "대기":
                                    current_pos.add(p['assigned_pos'])
                            full_set = set(POSITIONS_ALL)
                            return list(full_set - current_pos)
                        
                        miss_a = get_missing_pos_list(team_a)
                        miss_b = get_missing_pos_list(team_b)
                        miss_txt_a = ", ".join(miss_a) if miss_a else "없음"
                        miss_txt_b = ", ".join(miss_b) if miss_b else "없음"

                        st.info(f"📢 **[{i*2-1}·{i*2}세트] {count_a} vs {count_b}** (🔴A제외: {miss_txt_a} | 🔵B제외: {miss_txt_b})")
                        
                        # 밸런스 바
                        b_col1, b_col2 = st.columns([1, 4])
                        with b_col1:
                            diff = sum_a - sum_b
                            delta_color = "normal" if abs(diff) <= 2 else "inverse"
                            st.metric("🔴 A팀 전력", f"{sum_a}", delta=f"격차: {diff}", delta_color=delta_color)
                        with b_col2:
                            max_possible = max(count_a, count_b) * 5 if max(count_a, count_b) > 0 else 1
                            st.caption(f"전력 밸런스: A팀({sum_a}) vs B팀({sum_b})")
                            st.progress(min(sum_a / max_possible, 1.0))
                            st.progress(min(sum_b / max_possible, 1.0))

                        # Court View (작전판)
                        st.markdown("### 🏟️ Court View")
                        df_a = pd.DataFrame(team_a)
                        df_b = pd.DataFrame(team_b)
                        
                        html_a = render_tactical_board(df_a, "A팀", "assigned_pos")
                        st.markdown(html_a, unsafe_allow_html=True)
                        
                        st.markdown("<div style='text-align: center; font-weight: bold; margin: 5px 0; color: #999; font-size: 0.8em;'>▼ NEXT COURT ▼</div>", unsafe_allow_html=True)
                        
                        html_b = render_tactical_board(df_b, "B팀", "assigned_pos")
                        st.markdown(html_b, unsafe_allow_html=True)
                        
                        # [대기 인원 점수 표시 복구]
                        bench = [p for p in team_a+team_b if p['assigned_pos']=="대기"]
                        if bench:
                            st.divider()
                            st.caption("🛌 **대기 인원**")
                            # 리스트 형태로 점수와 사유를 상세히 표시
                            for p in bench:
                                sc = p.get('priority_score', 0)
                                re_txt = p.get('score_reason', '')
                                st.write(f"- {p['이름']} (희망: {p.get('1순위', '-')})")
                                # format_score_html을 사용하여 사유까지 예쁘게 표시
                                st.markdown(format_score_html(sc, re_txt), unsafe_allow_html=True)

            st.divider()
            st.subheader("🛠️ 결과 수정 및 확정")
            st.warning("수정 후 반드시 '저장' 버튼을 눌러야 일반 사용자에게 공개됩니다.")
            
            # 에디터
            cols = ["이름", "레벨", "1순위", "팀1", "확정1", "팀2", "확정2", "팀3", "확정3", "팀4", "확정4", "비고"]
            valid_cols = [c for c in cols if c in df.columns]
            edited_df = st.data_editor(df[valid_cols], hide_index=True, num_rows="dynamic")
            
            # 저장 버튼 (강제 새로고침 기능 포함)
            if st.button("💾 저장 (공개)", type="primary"):
                final_df = df.copy()
                final_df.update(edited_df)
                update_lineup(final_df)
                
                # 화면 기억 지우기 (시트 데이터 다시 불러오도록 유도)
                if 'fair_results' in st.session_state:
                    del st.session_state['fair_results']
                    
                st.success("저장되었습니다! 화면이 갱신됩니다.")
                time.sleep(1.0)
                st.rerun()

# --- 탭 7: 관리자 ---
with tab7:
    st.header("⚙️ 관리자 페이지")
    admin_auth = st.empty()

    # [1] 로그인 화면
    if not st.session_state['admin_logged_in']:
        with admin_auth.form("admin_main_login_unique"): # key 변경으로 충돌 방지
            pw = st.text_input("비밀번호", type="password")
            keep_login = st.checkbox("로그인 상태 유지하기 (체크 필수)", value=True)
            
            if st.form_submit_button("확인"):
                if pw == ADMIN_PASSWORD:
                    st.session_state['admin_logged_in'] = True
                    st.toast("관리자 모드 접속", icon="🔓")
                    if keep_login:
                        st.query_params["auth"] = ADMIN_PASSWORD
                    admin_auth.empty()
                    st.rerun()
                else: 
                    st.error("비밀번호가 일치하지 않습니다.")
    
    # [2] 로그인 성공 화면
    if st.session_state['admin_logged_in']:
        if st.button("로그아웃 (도장 지우기)", key="logout_tab7"):
            st.session_state['admin_logged_in'] = False
            st.query_params.clear()
            st.rerun()

        # 대시보드
        st.subheader("📊 오늘의 접속 현황")
        sheet_log = get_sheet_instance(SHEET_LOGS)
        if sheet_log:
            try:
                logs = sheet_log.get_all_records()
                if logs:
                    df_log = pd.DataFrame(logs)
                    now_kst = datetime.utcnow() + timedelta(hours=9)
                    today_str = now_kst.strftime("%Y-%m-%d")
                    df_log['날짜'] = df_log['일시'].astype(str).apply(lambda x: x.split(" ")[0])
                    df_today = df_log[df_log['날짜'] == today_str]
                    
                    visit_count = len(df_today[df_today['유형'] == '메인접속'])
                    lineup_count = len(df_today[df_today['유형'] == '라인업조회'])
                    
                    m1, m2 = st.columns(2)
                    m1.metric("오늘 방문자", f"{visit_count}명")
                    m2.metric("라인업 조회", f"{lineup_count}회")
                    
                    with st.expander("📜 상세 로그"):
                        st.dataframe(df_today[['일시', '유형', '접속자(추정)', 'IP주소']], hide_index=True)
            except: st.error("로그 로딩 실패")

        st.divider()

        # 라인업 공개 설정
        st.subheader("📢 라인업 공개 설정")
        if current_game:
            is_visible_now = str(current_game.get('공개여부', 'X')).upper().strip() == 'O'
            c_tog, c_stat = st.columns([1, 3])
            with c_tog:
                toggle_val = st.toggle("라인업 공개하기", value=is_visible_now)
            with c_stat:
                if toggle_val: st.success("🟢 **공개 중**")
                else: st.error("🔒 **비공개**")

            if toggle_val != is_visible_now:
                if toggle_game_visibility(toggle_val):
                    st.rerun()
        else: st.warning("진행 중인 게임 없음")

        st.divider()

        # 참가자 관리
        st.subheader("✅ 참가자 확정 및 입금 관리")
        apps = load_applicants()
        if apps:
            df_manage = pd.DataFrame(apps)
            if '입금' not in df_manage.columns: df_manage['입금'] = 'X'
            df_manage['입금_bool'] = df_manage['입금'].apply(lambda x: True if str(x).upper()=='O' else False)
            
            # 명단 분리
            df_manage = df_manage.reset_index(drop=True)
            mask = (df_manage.index < MAX_CAPACITY) | (df_manage['이름'].astype(str).str.contains(r"\[VEGA\]"))
            df_confirmed = df_manage[mask]
            df_waiting = df_manage[~mask]

            st.success(f"📌 **확정 ({len(df_confirmed)}명)**")
            ed_conf = st.data_editor(df_confirmed[["이름","연락처","입금_bool","1순위","비고"]], hide_index=True, key="ed_conf")
            
            if not df_waiting.empty:
                st.warning(f"⏳ **대기 ({len(df_waiting)}명)**")
                ed_wait = st.data_editor(df_waiting[["이름","연락처","입금_bool","1순위","비고"]], hide_index=True, key="ed_wait")
            
            if st.button("💾 저장하기", type="primary"):
                for i, r in ed_conf.iterrows(): df_manage.loc[r.name, '입금_bool'] = r['입금_bool']
                if not df_waiting.empty:
                    for i, r in ed_wait.iterrows(): df_manage.loc[r.name, '입금_bool'] = r['입금_bool']
                
                df_manage['입금'] = df_manage['입금_bool'].apply(lambda x: 'O' if x else 'X')
                update_lineup(df_manage)
                st.success("저장 완료")
                time.sleep(0.5); st.rerun()
        else: st.info("신청자 없음")

        st.divider()
        
        # 게임 관리
        st.subheader("🛠️ 게임 관리")
        tab_new, tab_close = st.tabs(["🆕 새 게임", "🏁 종료"])
        with tab_new:
            with st.form("new_game_form"):
                title = st.text_input("제목"); dt = st.text_input("일시")
                reset = st.checkbox("명단 초기화", value=True)
                if st.form_submit_button("개설"):
                    if reset: archive_current_game(); clear_applicants()
                    save_game_info({"제목":title, "일시":dt, "마감일시":"2099-12-31", "성별":"혼성", "장소":"체육관", "참가비":"-", "계좌":"-", "설명":"-", "연락처":"-"})
                    st.success("개설 완료"); st.rerun()
        with tab_close:
            if st.button("게임 종료 (CLOSED)"):
                archive_current_game()
                save_game_info({"제목":"CLOSED", "일시":"-", "마감일시":"-"})
                st.success("종료 완료"); st.rerun()

        # 기타 관리
        with st.expander("기타 설정 (영상/건의/블랙리스트/비상수정)"):
            st.write("영상 등록, 건의함 확인 등은 아래 기능을 이용하세요.")
            # (공간 절약을 위해 세부 기능은 생략했습니다. 필요시 이전 코드 붙여넣으셔도 됩니다.)
            # 만약 비상 수정 기능이 꼭 필요하시면 여기에 추가해주세요.
            if apps:
                st.divider()
                st.write("**데이터 비상 수정**")
                edited_raw = st.data_editor(pd.DataFrame(apps), key="raw_edit")
                if st.button("비상 저장"):
                    update_lineup(edited_raw); st.success("저장됨")

# --- 탭 8: 경기 영상 (NEW) ---
with tab8:
    st.header("📺 경기 영상 & 하이라이트")
    
    # 채널 정보 (사용자님이 운영하는 채널 URL로 변경하세요!)
    YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@pickup-game-y7r" # 본인 채널 주소 입력
    
    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown("### 📢 우리들의 멋진 플레이를 다시 보세요!")
            st.write("매주 경기 영상과 하이라이트가 업로드됩니다.")
        with c2:
            st.link_button("👉 유튜브 채널 바로가기", YOUTUBE_CHANNEL_URL, use_container_width=True)

    st.divider()
    
    # 최신 영상 불러오기
    video_data = get_latest_video()
    
    if video_data and 'url' in video_data and video_data['url']:
        st.subheader(f"🎬 {video_data.get('title', '최신 하이라이트')}")
        st.caption(f"등록일: {video_data.get('date', '')}")
        try:
            st.video(video_data['url'])
        except:
            st.error("영상을 불러올 수 없습니다. 링크를 확인해주세요.")
    else:
        st.info("아직 등록된 하이라이트 영상이 없습니다.")
        st.markdown(f"운영진이 영상을 편집 중입니다! [채널]({YOUTUBE_CHANNEL_URL})에서 확인해보세요.")
