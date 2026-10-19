import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import FinanceDataReader as fdr
import pandas as pd
import numpy as np

def collect_and_validate_stocks():
    # 1. 종목 리스트 정의
    stocks = [
        {"name": "삼성전기", "code": "009150"},
        {"name": "LG이노텍", "code": "011070"},
        {"name": "HT로보틱스", "code": "396300"},
        {"name": "대덕전자", "code": "353200"},
        {"name": "심텍", "code": "222800"},
        {"name": "롯데에너지머티리얼즈", "code": "020150"},
    ]

    # KRX 전체 종목 상장 정보 가져오기
    try:
        krx_df = fdr.StockListing("KRX")
        krx_df["Code"] = krx_df["Code"].astype(str).str.zfill(6)
        krx_df = krx_df.set_index("Code")
    except Exception as e:
        krx_df = pd.DataFrame()

    data_list = []
    errors = []

    for item in stocks:
        name = item["name"]
        code = str(item["code"]).zfill(6)

        row = {"종목명": name, "종목코드": code}
        try:
            # 2. 일별 시세 데이터 수집
            df = fdr.DataReader(code, "2026-01-01")

            if df is None or df.empty:
                raise ValueError("일별 시세 데이터 없음")

            latest_day = df.iloc[-1]
            prev_day = df.iloc[-2] if len(df) > 1 else latest_day

            # 가격 및 거래량 지표 매칭
            row["시가"] = int(latest_day.get("Open", 0)) if pd.notna(latest_day.get("Open")) else None
            row["고가"] = int(latest_day.get("High", 0)) if pd.notna(latest_day.get("High")) else None
            row["저가"] = int(latest_day.get("Low", 0)) if pd.notna(latest_day.get("Low")) else None
            current_close = latest_day.get("Close", None)
            row["현재가(종가)"] = int(current_close) if current_close is not None else None
            row["거래량"] = int(latest_day.get("Volume", 0)) if pd.notna(latest_day.get("Volume")) else None
            
            # 전일거래량
            prev_volume = prev_day.get("Volume", None)
            row["전일거래량"] = int(prev_volume) if prev_volume is not None else None

            # 거래대금
            if "Value" in latest_day:
                row["거래대금"] = int(latest_day.get("Value", 0))
            elif current_close and row["거래량"]:
                row["거래대금"] = int(current_close * row["거래량"])
            else:
                row["거래대금"] = None

            # 등락률 계산
            prev_close = prev_day.get("Close", None)
            if current_close is not None and prev_close is not None and prev_close != 0:
                change = round(((current_close - prev_close) / prev_close) * 100, 2)
                row["등락률(%)"] = change
                row["상승여부"] = change > 0
            else:
                row["등락률(%)"] = None
                row["상승여부"] = None

            # 3. KRX 상장 정보 매핑 (대소문자 차이 및 누락 방지 처리)
            marcap_val = None
            stocks_val = None
            foreign_ratio_val = None

            if not krx_df.empty and code in krx_df.index:
                krx_row = krx_df.loc[code]
                
                # 시가총액 (대소문자 및 다양한 컬럼명 대응)
                for col in ["Marcap", "marcap", "MARCAP"]:
                    if col in krx_row and pd.notna(krx_row[col]):
                        marcap_val = krx_row[col]
                        break

                # 상장주식수
                for col in ["Stocks", "stocks", "STOCKS", "Shares"]:
                    if col in krx_row and pd.notna(krx_row[col]):
                        stocks_val = krx_row[col]
                        break

                # 외국인비율 (데이터셋에 있는 경우)
                for col in ["ForeignRatio", "foreign_ratio", "Foreign"]:
                    if col in krx_row and pd.notna(krx_row[col]):
                        foreign_ratio_val = krx_row[col]
                        break

            # 시가총액이 없는데 현재가와 상장주식수가 있다면 직접 계산해서 채우기 (현재가 * 상장주식수)
            if marcap_val is None and current_close and stocks_val:
                marcap_val = int(current_close * stocks_val)

            row["시가총액"] = int(marcap_val) if marcap_val is not None else None
            row["상장주식수"] = int(stocks_val) if stocks_val is not None else None
            
            # 일별 데이터프레임 내에 외국인 관련 컬럼이 있는지 확인 후 매핑
            if foreign_ratio_val is None:
                for col in ["ForeignRatio", "Foreign", "Foreigner"]:
                    if col in latest_day and pd.notna(latest_day[col]):
                        foreign_ratio_val = latest_day[col]
                        break

            row["외국인비율"] = float(foreign_ratio_val) if foreign_ratio_val is not None else None

            data_list.append(row)
            
        except Exception as e:
            errors.append(f"{name}({code}) 수집 실패: {e}")

    # 4. 결과 데이터프레임 생성 및 CSV 저장
    df_result = pd.DataFrame(data_list)
    csv_filename = "electronic_equipment_multi_detailed.csv"
    df_result.to_csv(csv_filename, index=False, encoding="utf-8-sig")

    # 5. 검증 체크리스트
    expected_count = len(stocks)
    actual_count = len(df_result)
    if actual_count != expected_count:
        errors.append(f"수집 건수 불일치: 기대({expected_count}) != 실제({actual_count})")

    if not df_result.empty and "등락률(%)" in df_result.columns:
        invalid_changes = df_result[df_result["등락률(%)"].notna() & (abs(df_result["등락률(%)"]) > 30)]
        if not invalid_changes.empty:
            errors.append("가격제한폭(±30%) 초과 종목 발견")

    # 6. 상태 메시지 반환
    if errors:
        status_message = "[경고] 오류 발생: " + ", ".join(errors)
        is_error = True
    else:
        status_message = f"[정상] {actual_count}/{expected_count} 종목 핵심 지표 수집 완료"
        is_error = False

    return status_message, is_error, csv_filename

# --- [실행부] 수집/검증 및 메일 발송 ---
if __name__ == "__main__":
    result_msg, has_error, attached_file = collect_and_validate_stocks()
    print("=== 데이터 수집 및 검증 결과 ===")
    print(result_msg)

    # 메일 발송 설정
    try:
        msg = MIMEMultipart()

        EMAIL_SENDER = os.environ.get("EMAIL_USER", "")
        EMAIL_RECEIVER = os.environ.get("RECIPIENT_EMAIL", "")
        EMAIL_PASSWORD = os.environ.get("EMAIL_PASS", "")

        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg["Subject"] = f"주식 핵심 데이터 수집 및 검증 보고 - {result_msg}"

        body = (
            "안녕하세요, 오늘의 주식 데이터 크롤링 및 검증 결과입니다.\n\n"
            f"상태: {result_msg}\n\n"
            "시가총액 및 상세 지표가 보완된 CSV 파일을 첨부합니다."
        )
        msg.attach(MIMEText(body, "plain"))

        # CSV 파일 첨부
        if os.path.exists(attached_file):
            with open(attached_file, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={attached_file}")
            msg.attach(part)
            print(f"[{attached_file}] 파일이 메일에 첨부되었습니다.")

        server = smtplib.SMTP_SSL("smtp.naver.com", 465)
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        server.quit()
        print("[메일 발송 성공] CSV 파일이 첨부된 갱신 결과 메일이 전송되었습니다.")

    except Exception as e:
        print(f"[메일 발송 실패] 사유: {e}")
