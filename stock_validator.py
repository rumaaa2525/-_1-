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
# GitHub 로그에 맞게 파일 이름을 정확히 일치시켰습니다.
CSV_PATH = "electronic_equipment_multi.csv"

# 전자장비와기기 업종 코드
TARGET_GROUP_CODE = '282' 

SMTP_SERVER = "smtp.naver.com"
SMTP_PORT = 465
EMAIL_USER = os.environ.get("EMAIL_USER", "your_naver@naver.com")
EMAIL_PASS = os.environ.get("EMAIL_PASS", "your_app_password")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "receiver@naver.com")

# --- [기능 함수 영역] ---

def get_naver_group_stocks(group_code):
    """네이버 증권에서 업종 내 종목 리스트를 가져옴 (더 강력한 버전)"""
    # URL 형식을 다시 확인합니다.
    url = f"https://finance.naver.com/sise/sise_group_detail.naver?groupCode={group_code}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    try:
        res = requests.get(url, headers=headers)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 종목 리스트가 들어있는 테이블을 더 넓게 탐색합니다.
        stocks = []
        # 네이버 금융의 업종 상세 페이지는 table.type_group 구조를 가집니다.
        rows = soup.find_all('tr')
        
        for row in rows:
            a_tag = row.find('a')
            if a_tag and 'code=' in a_tag.get('href', ''):
                name = a_tag.text.strip()
                code = a_tag.get('href').split('code=')[-1]
                if name and code:
                    stocks.append({"name": name, "code": code})
        
        return stocks
    except Exception as e:
        print(f"업종 리스트 추출 중 오류 발생: {e}")
        return []

def get_financial_indicators(code):
    """재무 지표 크롤링 (기존과 동일)"""
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
    """이메일 발송 (SSL 보안 방식)"""
    if not EMAIL_USER or not EMAIL_PASS: return
    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = RECIPIENT_EMAIL
    msg['Subject'] = f"[주식 보고서] {datetime.now().strftime('%Y-%m-%d')} 수집 결과"

    error_detail = "\n".join([f"- {err}" for err in error_list[:10]]) if error_list else "없음"
    body_text = f"안녕하세요. 자동 수집 시스템입니다.\n\n[수집 요약]\n- 일자: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n- 성공: {success}개\n- 실패: {fail}개\n\n[오류 내역]\n{error_detail}\n\n첨부파일을 확인하세요."
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

def collect_and_validate_stocks():
    today_str = datetime.now().strftime('%Y-%m-%d')
    print(f"[{today_str}] 시작")

    stocks = get_naver_group_stocks(TARGET_GROUP_CODE)
    
    # 중요: 여기서 종목을 못 찾으면 에러 메시지를 남겨야 합니다.
    if not stocks:
        print(f"❌ 오류: '{TARGET_GROUP_CODE}' 업종의 종목을 하나도 찾지 못했습니다. 코드를 확인하세요.")
        return

    print(f"✅ {len(stocks)}개 종목 발견. 데이터 수집 중...")
    data_list, errors = [], []

    for item in stocks:
        name, code = item["name"], str(item["code"]).zfill(6)
        try:
            df = fdr.DataReader(code, "2025-01-01")
            if len(df) < 2: continue
            latest, prev = df.iloc[-1], df.iloc[-2]
            ind = get_financial_indicators(code)

            data_list.append({
                "수집 날짜": today_str, "종목코드": code, "종목명": name,
                "기준가": int(prev["Close"]), "시가": int(latest["Open"]),
                "고가": int(latest["High"]), "저가": int(latest["Low"]),
                "현재가": int(latest["Close"]), "거래량": int(latest["Volume"]),
                "거래대금": int(latest["Volume"] * latest["Close"]),
                "52주 최고": int(df["High"].max()), "시가총액": ind["시가총액"],
                "외인소진율": ind["외인소진율"], "PER": ind["PER"], "EPS": ind["EPS"],
                "추정PER": ind["추정PER"], "추정EPS": ind["추정EPS"], "PBR": ind["PBR"],
                "BPS": ind["BPS"], "배당수익률": ind["배당수익률"], "주당 배당금": ind["주당 배당금"]
            })
            time.sleep(0.3)
        except Exception as e:
            errors.append(f"{name}: {e}")

    if data_list:
        pd.DataFrame(data_list).to_csv(CSV_PATH, index=False, encoding='utf-8-sig')
        print(f"✅ 저장 완료: {CSV_PATH}")
    
    send_email(CSV_PATH, len(data_list), len(errors), errors)

if __name__ == "__main__":
    collect_and_validate_stocks()
