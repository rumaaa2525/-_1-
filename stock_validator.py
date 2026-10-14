import os
import smtplib
import time
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import FinanceDataReader as fdr
import pandas as pd
import requests
from bs4 import BeautifulSoup

# --- [설정 영역] ---
# 1. 결과 저장 파일명
CSV_PATH = "electronic_equipment_full_data.csv"

# 2. 업종 코드 (사용자님이 제공해주신 전자장비와기기 코드 282 반영 완료)
TARGET_GROUP_CODE = '282' 

# 3. 이메일 설정 (GitHub Secrets에 등록하여 사용하는 것을 권장)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_USER = os.environ.get("EMAIL_USER", "your_email@gmail.com")
EMAIL_PASS = os.environ.get("EMAIL_PASS", "your_password")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "receiver@gmail.com")

# --- [기능 함수 영역] ---

def get_naver_group_stocks(group_code):
    """네이버 증권에서 업종 내 종목 리스트를 자동으로 가져옴"""
    url = f"https://finance.naver.com/sise/sise_group_detail.naver?groupCode={group_code}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        res = requests.get(url, headers=headers)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')
        stocks = []
        rows = soup.select('table.type_group tr')
        for row in rows:
            name_tag = row.select_one('a')
            if name_tag:
                name = name_tag.text.strip()
                code_href = name_tag.get('href', '')
                if 'code=' in code_href:
                    code = code_href.split('code=')[-1]
                    stocks.append({"name": name, "code": code})
        return stocks
    except Exception as e:
        print(f"업종 리스트 가져오기 실패: {e}")
        return []

def get_financial_indicators(code):
    """네이버 종목 상세 페이지에서 재무 지표(PER, PBR, 배당 등)를 크롤링"""
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    indicators = {
        "시가총액": "0", "외인소진율": "0%", "PER": "0", "PBR": "0", 
        "EPS": "0", "BPS": "0", "배당수익률": "0%", "주당 배당금": "0",
        "추정PER": "-", "추정EPS": "-", "거래대금": "0"
    }
    
    try:
        res = requests.get(url, headers=headers)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')

        summary_table = soup.select_one('table.type2.summary')
        if summary_table:
            rows = summary_table.select('tr')
            for row in rows:
                cols = row.select('th, td')
                if len(cols) >= 2:
                    label = cols[0].text.strip()
                    value = cols[1].text.strip().replace(',', '')
                    if '시가총액' in label: indicators["시가총액"] = value
                    elif 'PER' in label: indicators["PER"] = value
                    elif 'PBR' in label: indicators["PBR"] = value
                    elif 'EPS' in label: indicators["EPS"] = value
                    elif 'BPS' in label: indicators["BPS"] = value
                    elif '배당수익률' in label: indicators["배당수익률"] = value
                    elif '주당배당금' in label: indicators["주당 배당금"] = value

        foreign_th = soup.find('th', text='외국인보유비율')
        if foreign_th:
            indicators["외인소진율"] = foreign_th.find_next_sibling('td').text.strip()

    except Exception as e:
        print(f"  [!] 상세지표 크롤링 오류({code}): {e}")
    
    return indicators

def send_email(file_path, success, fail, error_list):
    """수집 결과 요약을 포함하여 이메일 전송"""
    if not EMAIL_USER or not EMAIL_PASS:
        print("이메일 설정이 되어 있지 않아 전송을 건너뜁니다.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = RECIPIENT_EMAIL
    msg['Subject'] = f"[주식 보고서] {datetime.now().strftime('%Y-%m-%d')} 업종 데이터 수집 결과"

    # --- [메일 본문 구성 - 문법 오류 완벽 수정] ---
    error_detail = ""
    if error_list:
        error_detail = "\n".join([f"- {err}" for err in error_list[:10]])
        if len(error_list) > 10:
            error_detail += f"\n... 외 {len(error_list)-10}건"
    else:
        error_detail = "없음"

    # 세 개의 따옴표(""")를 사용하여 줄바꿈 에러를 방지합니다.
    body_text = f"""
안녕하세요, 자동 수집 시스템입니다.

금일 주식 데이터 수집 결과 보고드립니다.

[수집 요약]
- 수집 일자: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 총 대상 종목: {success + fail}개
- 수집 성공: {success}개
- 수집 실패: {fail}개

[상세 오류 내역]
{error_detail}

상세 데이터는 첨부된 CSV 파일을 확인해 주세요.
"""
    msg.attach(MIMEText(body_text, 'plain'))

    # --- [첨부파일 추가] ---
    try:
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                part = MIMEApplication(f.read(), _subtype="csv")
                part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(file_path))
                msg.attach(part)

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
        server.quit()
        print("📧 이메일 전송 성공!")
    except Exception as e:
        print(f"📧 이메일 전송 실패: {e}")

def collect_and_validate_stocks():
    """전체 수집 및 검증 프로세스"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    print(f"[{today_str}] 데이터 수집 프로세스 시작")

    stocks = get_naver_group_stocks(TARGET_GROUP_CODE)
    if not stocks:
        print("업종 종목을 찾을 수 없습니다.")
        return

    data_list = []
    errors = []

    for item in stocks:
        name = item["name"]
        code = str(item["code"]).zfill(6)
        print(f"진행 중: {name}({code})")

        try:
            df = fdr.DataReader(code, "2025-01-01")
            if len(df) < 2:
                raise ValueError("데이터 부족")

            latest = df.iloc[-1]
            prev = df.iloc[-2]
            ind = get_financial_indicators(code)

            data_list.append({
                "수집 날짜": today_str,
                "종목코드": code,
                "종목명": name,
                "기준가": int(prev["Close"]),
                "시가": int(latest["Open"]),
                "고가": int(latest["High"]),
                "저가": int(latest["Low"]),
                "현재가": int(latest["Close"]),
                "거래량": int(latest["Volume"]),
                "거래대금": int(latest["Volume"] * latest["Close"]),
                "52주 최고": int(df["High"].max()),
                "시가총액": ind["시가총액"],
                "외인소진율": ind["외인소진율"],
                "PER": ind["PER"],
                "EPS": ind["EPS"],
                "추정PER": ind["추정PER"],
                "추정EPS": ind["추정EPS"],
                "PBR": ind["PBR"],
                "BPS": ind["BPS"],
                "배당수익률": ind["배당수익률"],
                "주당 배당금": ind["주당 배당금"]
            })
            time.sleep(0.4)

        except Exception as e:
            errors.append(f"{name}({code}): {e}")

    success_count = len(data_list)
    fail_count = len(errors)

    if data_list:
        df_final = pd.DataFrame(data_list)
        df_final.to_csv(CSV_PATH, index=False, encoding='utf-8-sig')
        print(f"✅ {success_count}개 종목 저장 완료.")
    
    send_email(CSV_PATH, success_count, fail_count, errors)

if __name__ == "__main__":
    collect_and_validate_stocks()

        print("[메일 발송 성공] 서버가 메일 발송 요청을 수락했습니다.")

    except Exception as e:
        print(f"[메일 발송 실패] 사유: {e}")
        raise
