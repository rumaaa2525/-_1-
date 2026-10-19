import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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

    # KRX 전체 종목 상장 정보 (시가총액, PER, PBR, ROE, 배당수익률 등 포함) 미리 가져오기
    try:
        krx_df = fdr.StockListing("KRX")
        # 종목코드를 6자리 문자열로 패딩
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
            # 2. 일별 시세 데이터 수집 (Open, High, Low, Close, Volume 등)
            df = fdr.DataReader(code, "2026-01-01")

            if df is None or df.empty:
                raise ValueError("일별 시세 데이터 없음")

            latest_day = df.iloc[-1]
            prev_day = df.iloc[-2] if len(df) > 1 else latest_day

            # 기본 가격 및 거래 정보 (사진 속 항목 매칭)
            row["시가"] = int(latest_day.get("Open", 0)) if pd.notna(latest_day.get("Open")) else None
            row["고가"] = int(latest_day.get("High", 0)) if pd.notna(latest_day.get("High")) else None
            row["저가"] = int(latest_day.get("Low", 0)) if pd.notna(latest_day.get("Low")) else None
            current_close = latest_day.get("Close", None)
            row["현재가(종가)"] = int(current_close) if current_close is not None else None
            row["거래량"] = int(latest_day.get("Volume", 0)) if pd.notna(latest_day.get("Volume")) else None
            
            # 전일거래량
            prev_volume = prev_day.get("Volume", None)
            row["전일거래량"] = int(prev_volume) if prev_volume is not None else None

            # 거래대금 (종가 * 거래량 대략 계산 또는 컬럼 존재 시 활용)
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

            # 3. KRX 상장 정보 및 재무 지표 매핑 (시가총액, PER, PBR, 외국인비율 등 사진 속 항목)
            if not krx_df.empty and code in krx_df.index:
                krx_row = krx_df.loc[code]
                row["시가총액"] = krx_row.get("Marcap", None)
                row["상장주식수"] = krx_row.get("Stocks", None)
                row["PER"] = krx_row.get("PER", None)
                row["PBR"] = krx_row.get("PBR", None)
                row["배당수익률"] = krx_row.get("Dividend", None)
                row["외국인비율"] = krx_row.get("ForeignRatio", None)
            else:
                row["시가총액"] = None
                row["상장주식수"] = None
                row["PER"] = None
                row["PBR"] = None
                row["배당수익률"] = None
                row["외국인비율"] = None

            # 추가 재무제표 항목 (매출액, 영업이익, 당기순이익, ROE, ROA 등은 기본 API에서 제한될 수 있으므로 예외 처리 동반)
            # 필요에 따라 OpenDart나 별도 재무 크롤링 연동 가능 영역
            for metric in ["매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "유보율", "ROE", "ROA", "주당순이익", "매출액증가율", "영업이익증가율", "보통주배당금"]:
                row[metric] = krx_row.get(metric, None) if ('krx_row' in locals() and metric in krx_row) else None

            data_list.append(row)
            
        except Exception as e:
            errors.append(f"{name}({code}) 수집 실패: {e}")

    # 4. 결과 데이터프레임 생성 및 CSV 저장
    df_result = pd.DataFrame(data_list)
    csv_filename = "electronic_equipment_multi_detailed.csv"
    df_result.to_csv(csv_filename, index=False, encoding="utf-8-sig")

    # 5. 검증 체크리스트 수행
    expected_count = len(stocks)
    actual_count = len(df_result)
    if actual_count != expected_count:
        errors.append(f"수집 건수 불일치: 기대({expected_count}) != 실제({actual_count})")

    # 상하한가(±30%) 초과 검증
    if not df_result.empty and "등락률(%)" in df_result.columns:
        invalid_changes = df_result[df_result["등락률(%)"].notna() & (abs(df_result["등락률(%)"]) > 30)]
        if not invalid_changes.empty:
            errors.append("가격제한폭(±30%) 초과 종목 발견")

    # 6. 상태 메시지 반환
    if errors:
        status_message = "[경고] 오류 발생: " + ", ".join(errors)
        is_error = True
    else:
        status_message = f"[정상] {actual_count}/{expected_count} 종목 확장 지표 수집 완료"
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

        EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
        EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")
        EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg["Subject"] = f"주식 상세 데이터 수집 및 검증 보고 - {result_msg}"

        body = (
            "안녕하세요, 오늘의 주식 확장 지표 크롤링 및 검증 결과입니다.\n\n"
            f"상태: {result_msg}\n\n"
            "요청하신 사진 속 주요 지표(시가, 고가, 저가, 거래량, 시가총액, PER, PBR, 외국인비율 등)가 포함된 CSV 파일이 갱신되었습니다."
        )
        msg.attach(MIMEText(body, "plain"))

        # 필요시 수집된 CSV 파일을 이메일에 첨부하고 싶다면 아래 주석을 해제하세요.
        # from email.mime.base import MIMEBase
        # from email import encoders
        # with open(attached_file, "rb") as f:
        #     part = MIMEBase("application", "octet-stream")
        #     part.set_payload(f.read())
        # encoders.encode_base64(part)
        # part.add_header("Content-Disposition", f"attachment; filename= {attached_file}")
        # msg.attach(part)

        server = smtplib.SMTP_SSL("smtp.naver.com", 465)
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        server.quit()
        print("[메일 발송 성공] 갱신된 결과 메일이 전송되었습니다.")

    except Exception as e:
        print(f"[메일 발송 실패] 사유: {e}")
