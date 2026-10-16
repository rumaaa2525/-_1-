import os
import smtplib
import time
import ssl
import json
import pandas as pd
import requests
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

# --- [설정 영역] ---
CSV_PATH = "electronic_equipment_multi.csv"
TARGET_URL = "https://stock.naver.com/market/stock/kr/industry/49?no=282"

SMTP_SERVER = "smtp.naver.com"
SMTP_PORT = 465
EMAIL_USER = os.environ.get("MY_EMAIL_SENDER", "your_naver@naver.com")
EMAIL_PASS = os.environ.get("MY_EMAIL_PW", "your_app_password")
RECIPIENT_EMAIL = os.environ.get("MY_EMAIL_RECEIVER", "receiver@naver.com")

# --- [기능 함수 영역] ---

def get_stocks_from_url(url):
    """네이버 업종 페이지에서 종목 리스트 추출"""
    print(f"🌐 업종 페이지 접속 중: {url}")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
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

def get_naver_chart_data(code):
    """⭐ 사용자님이 가져오신 방식: 네이버 차트 API로 시세 데이터 직접 추출"""
    # 최근 5일치 데이터를 가져오기 위해 날짜 설정
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - pd.Timedelta(days=10)).strftime('%Y%m%d')
    
    url = f"https://m.stock.naver.com/front-api/external/chart/domestic/info?symbol={code}&requestType=1&startTime={start_date}&endTime={end_date}&timeframe=day"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        data = res.json()
        
        # API 응답 구조에서 데이터 추출 (data['data'] 안에 리스트가 들어있음)
        chart_data = data.get('data', [])
        if not chart_data:
            return None, None
            
        # 가장 최근(마지막) 데이터와 그 전날 데이터 추출
        latest = chart_data[-1]
        prev = chart_data[-2]
        
        return latest, prev
    except Exception as e:
        print(f"  [!] 시세 API 오류({code}): {e}")
        return None, None

def get_financial_indicators(code):
    """재무 지표 크롤링 (기존 방식 유지)"""
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    indicators = {"시가총액": "0", "외인소진율": "0%", "PER": "0", "PBR": "0", "EPS": "0", "BPS": "0", "배당수익률": "0%", "주당 배당금": "0", "추정PER": "-", "추정EPS": "-", "거래대금": "0"}
    try:
        res = requests.get(url, headers=headers)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')
        summary_table = soup.select_one('table.type2.summary')
        if summary_table:
            for row in summary_table.select('tr'):
                cols = row.select('th, td')
                if len(cols) >= 2:
                    label, value = cols[0].text.strip(), cols[1].text.strip().replace(',', '')
                    if '시가총액' in label: indicators["시가총액"] = value
                    elif 'PER' in label: indicators["PER"] = value
                    elif 'PBR' in label: indicators["PBR"] = value
                    elif 'EPS' in label: indicators["EPS"] = value
                    elif 'BPS' in label: indicators["BPS"] = value
                    elif '배당수익률' in label: indicators["배당수익률"] = value
                    elif '주당배당금' in label: indicators["주당 배당금"] = value
        foreign_th = soup.find('th', text='외국인보유비율')
        if foreign_th: indicators["외인소진율"] = foreign_th.find_next_sibling('td').text.strip()
    except: pass
    return indicators

def send_email(file_path, success, fail, error_list):
    """이메일 발송"""
    if not EMAIL_USER or not EMAIL_PASS: return
    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = RECIPIENT_EMAIL
    msg['Subject'] = f"[📊 주식 보고서] {datetime.now().strftime('%Y-%m-%d')} 수집 완료"

    error_text = "\n".join([f"- {err}" for err in error_list[:10]]) if error_list else "없음"
    body_text = (
        f"안녕하세요, 자동 수집 시스템입니다.\n\n"
        f"금일 주식 데이터 수집 결과 보고드립니다.\n\n"
        f"[수집 요약]\n"
        f"- 수집 일자: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- 총 대상 종목: {success + fail}개\n"
        f"- 수집 성공: {success}개\n"
        f"- 수집 실패: {fail}개\n\n"
        f"[상세 오류 내역]\n"
        f"{error_text}\n\n"
        f"상세 데이터는 첨부된 CSV 파일을 확인해 주세요."
    )
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
    print(f"🚀 [{today}] 데이터 수집 프로세스 시작 (네이버 API 통합 버전)")

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
            # ⭐ 핵심: 사용자님의 코드를 활용한 API 방식 호출
            latest, prev = get_naver_chart_data(code)
            
            if not latest or not prev:
                raise ValueError("차트 데이터를 가져올 수 없습니다.")

            # 재무 데이터 가져오기
            ind = get_financial_indicators(code)

            data_list.append({
                "수집 날짜": today, "종목코드": code, "종목명": name,
                "기준가": int(prev['close']), # API 필드명 확인 필요 (보통 소문자)
                "시가": int(latest['open']),
                "고가": int(latest['high']),
                "저가": int(latest['low']),
                "현재가": int(latest['close']),
                "거래량": int(latest['volume']),
                "거래대금": int(latest['volume'] * latest['close']),
                "52주 최고": int(max([d.get('high', 0) for d in [prev, latest] if d])), # 단순화
                "시가총액": ind["시가총액"],
                "외인소진율": ind["외인소진율"], "PER": ind["PER"], "EPS": ind["EPS"],
                "추정PER": ind["추정PER"], "추정EPS": ind["추정EPS"], "PBR": ind["PBR"],
                "BPS": ind["BPS"], "배당수익률": ind["배당수익률"], "주당 배당금": ind["주당 배당금"]
            })
            time.sleep(0.4)
        except Exception as e:
            errors.append(f"{name}({code}): {e}")

    if data_list:
        pd.DataFrame(data_list).to_csv(CSV_PATH, index=False, encoding='utf-utf-sig')
        print(f"✅ {len(data_list)}개 종목 저장 완료: {CSV_PATH}")
    
    send_email(CSV_PATH, len(data_list), len(errors), errors)

if __name__ == "__main__":
    main()

