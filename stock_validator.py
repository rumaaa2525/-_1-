import os
import smtplib
import time
import ssl
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import FinanceDataReader as fdr
import pandas as pd
import requests
from bs4 import BeautifulSoup

# --- [설정 영역] ---
CSV_PATH = "electronic_equipment_multi.csv"
TARGET_URL = "https://stock.naver.com/market/stock/kr/industry/49?no=282"

SMTP_SERVER = "smtp.naver.com"
SMTP_PORT = 465
EMAIL_USER = os.environ.get("EMAIL_USER", "your_naver@naver.com")
EMAIL_PASS = os.environ.get("EMAIL_PASS", "your_app_password")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "receiver@naver.com")

# --- [기능 함수 영역] ---

def get_stocks_from_url(url):
    """주소에서 종목 리스트 추출"""
    print(f"🌐 주소 접속 중: {url}")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        res = requests.get(url, headers=headers)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        stocks = []
        links = soup.find_all('a', href=True)
        for link in links:
            href = link.get('href')
            if 'code=' in href:
                code = href.split('code=')[-1]
                name = link.text.strip()
                if name and len(code) == 6 and code.isdigit():
                    if not any(s['code'] == code for s in stocks):
                        stocks.append({"name": name, "code": code})
        return stocks
    except Exception as e:
        print(f"❌ 종목 추출 실패: {e}")
        return []

def get_comprehensive_data(code):
    """체크리스트의 모든 재무/시세 데이터를 통합 수집"""
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    # 기본 데이터 구조 (체크리스트 항목 모두 포함)
    data = {
        "거래량": 0, "거래대금": 0, "시가총액": 0, "매출액": 0, "영업이익가율": 0, "시가": 0, "고가": 0,
        "저가": 0, "매수호가": 0, "매도호가": 0, "매수총잔량": 0, "매도총잔량": 0, "전일거래량": 0, "외국인비율": 0,
        "상장주식수": 0, "자산총계": 0, "부채총계": 0, "매출액증가율": 0, "영업이익": 0, "당기순이익": 0,
        "주당순이익": 0, "보통주배당금": 0, "PER": 0, "ROE": 0, "ROA": 0, "PBR": 0, "유보율": 0
    }

    try:
        res = requests.get(url, headers=headers)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')

        # 1. 시세 데이터 (FinanceDataReader 활용)
        df = fdr.DataReader(code, "2025-01-01")
        if len(df) >= 2:
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            data["거래량"] = int(latest["Volume"])
            data["거래대금"] = int(latest["Volume"] * latest["Close"])
            data["시가"] = int(latest["Open"])
            data["고가"] = int(latest["High"])
            data["저가"] = int(latest["Low"])
            data["전일거래량"] = int(prev["Volume"])
            # 호가 데이터는 웹 크롤링 특성상 변동성이 매우 커서 실시간 수집이 어려우나 
            # 여기서는 종가 기준으로 대체하거나 0으로 설정합니다.
            data["매수호가"] = int(latest["Close"]) 
            data["매도호가"] = int(latest["Close"])

        # 2. 재무 지표 (네이버 기업실적분석 테이블 크롤링)
        # 네이버 금융의 '주요재무정보' 테이블을 찾습니다.
        tables = soup.select('table.type2')
        for table in tables:
            rows = table.select('tr')
            for row in rows:
                cols = row.select('th, td')
                if len(cols) >= 2:
                    label = cols[0].text.strip()
                    value = cols[1].text.strip().replace(',', '')
                    
                    # 매핑 로직
                    if '시가총액' in label: data["시가총액"] = value
                    elif '매출액' in label: data["매출액"] = value
                    elif '영업이익' in label: data["영업이익"] = value
                    elif '당기순이익' in label: data["당기순이익"] = value
                    elif '자산총계' in label: data["자산총계"] = value
                    elif '부채총계' in label: data["부채총계"] = value
                    elif 'PER' in label: data["PER"] = value
                    elif 'ROE' in label: data["ROE"] = value
                    elif 'ROA' in label: data["ROA"] = value
                    elif 'PBR' in label: data["PBR"] = value
                    elif '유보율' in label: data["유보율"] = value
                    elif '주당순이익' in label: data["주당순이익"] = value
                    elif '보통주배당금' in label: data["보통주배당금"] = value
                    # 추가 항목들 (필요시 매핑)
                    elif '매출액증가율' in label: data["매출액증가율"] = value
                    elif '영업이익률' in label: data["영업이익가율"] = value

        # 외국인 비율 추출
        foreign_th = soup.find('th', text='외국인보유비율')
        if foreign_th:
            data["외인소진율"] = foreign_th.find_next_sibling('td').text.strip()

    except Exception as e:
        print(f"  [!] 데이터 수집 오류({code}): {e}")
    
    return data

def send_email(file_path, success, fail, error_list):
    """이메일 발송"""
    if not EMAIL_USER or not EMAIL_PASS: return
    msg = MIMemultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = RECIPIENT_EMAIL
    msg['Subject'] = f"[📊 종합 주식 리포트] {datetime.now().strftime('%Y-%m-%d')} 수집 완료"

    error_text = "\n".join([f"- {err}" for err in error_list[:10]]) if error_list else "없음"
    body_text = f"""
안녕하세요, 자동 수집 시스템입니다.

금일 요청하신 모든 항목(재무/시세/외인 등)에 대한 수집이 완료되었습니다.

[수집 요약]
- 일자: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 성공: {success}개
- 실패: {fail}개

[상세 오류 내역]
{error_text}

상세한 데이터는 첨부된 CSV 파일을 확인해 주시기 바랍니다.
"""
    msg.attach(MIMEText(body_text, 'plain'))

    try:
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                part = MIMEApplication(f.read(), _subtype="csv")
                part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(file_path))
                msg.attach(part)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
        print("📧 이메일 전송 성공!")
    except Exception as e:
        print(f"📧 이메일 전송 실패: {e}")

def main():
    today = datetime.now().strftime('%Y-%m-%d')
    print(f"🚀 [{today}] 전방위 데이터 수집 프로세스 시작")

    stocks = get_stocks_from_url(TARGET_URL)
    if not stocks:
        print("❌ 종목을 찾지 못했습니다.")
        return

    print(f"✅ {len(stocks)}개 종목 발견. 수집을 시작합니다.")
    data_list, errors = [], []

    for item in stocks:
        name, code = item["name"], str(item["code"]).zfill(6)
        print(f"  - {name}({code}) 수집 중...")
        try:
            info = get_comprehensive_data(code)
            # 기본 정보 결합
            info.update({"수집 날짜": today, "종목코드": code, "종목명": name})
            data_list.append(info)
            time.sleep(0.5) # 차단 방지
        except Exception as e:
            errors.append(f"{name}({code}): {e}")

    if data_list:
        df = pd.DataFrame(data_list)
        # 컬럼 순서 정렬 (보기 좋게)
        cols = ["수집 날짜", "종목코드", "종목명", "시가", "고가", "저가", "현재가", "거래량", "거래대금", "시가총액", "PER", "PBR", "ROE", "ROA", "외인소진율"]
        # 실제 데이터에 있는 컬럼만 추출하여 저장
        existing_cols = [c for c in cols if c in df.columns] + [c for c in df.columns if c not in cols]
        df[existing_cols].to_csv(CSV_PATH, index=False, encoding='utf-8-sig')
        print(f"✅ 저장 완료: {CSV_PATH}")
    
    send_email(CSV_PATH, len(data_list), len(errors), errors)

if __name__ == "__main__":
    main()

