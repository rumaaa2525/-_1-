import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import FinanceDataReader as fdr
import pandas as pd

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

    # 확장 지표 목록: 수집 가능한 지표를 키로 사용
    extra_metrics = [
        "Open", "High", "Low", "Close", "Volume",
        "MarketCap", "Revenue", "OperatingIncome", "NetIncome",
        "PER", "ROE", "ROA", "DebtRatio"
    ]

    data_list = []
    errors = []

    for item in stocks:
        name = item["name"]
        code = str(item["code"]).zfill(6)

        row = {"종목명": name, "종목코드": code}
        try:
            df = fdr.DataReader(code, "2026-01-01")

            if df is None or df.empty:
                raise ValueError("데이터 없음")

            latest_day = df.iloc[-1]
            prev_day = df.iloc[-2]

            # 기본 가격 정보
            current_close = latest_day.get("Close", None)
            price = int(current_close) if current_close is not None else None
            row["현재가"] = price

            # 등락률 계산
            prev_close = prev_day.get("Close", None)
            if current_close is not None and prev_close is not None and prev_close != 0:
                change = round(((current_close - prev_close) / prev_close) * 100, 2)
                row["등락률(%)"] = change
                row["상승여부"] = change > 0
            else:
                row["등락률(%)"] = None
                row["상승여부"] = None

            # 확장 지표 수집 시도
            for met in extra_metrics:
                value = None
                if met in df.columns:
                    value = df.iloc[-1].get(met)
                else:
                    value = float("nan")
                row[met] = value

            data_list.append(row)
        except Exception as e:
            errors.append(f"{name}({code}) 수집 실패: {e}")

    # 3. 새로운 결과로 CSV 파일 생성
    df_result = pd.DataFrame(data_list)
    df_result.to_csv(
        "electronic_equipment_multi.csv", index=False, encoding="utf-8-sig"
    )

    # 4. 검증 체크리스트 수행
    expected_count = 6
    actual_count = len(df_result)
    if actual_count != expected_count:
        errors.append(f"수집 건수 불일치: 기대({expected_count}) != 실제({actual_count})")

    missing_count = df_result.isnull().sum().sum()
    if missing_count > 0:
        errors.append(f"결측치 발견: {missing_count}건")

    # 상하한가(±30%) 초과 검증
    if not df_result.empty and "등락률(%)" in df_result.columns:
        invalid_changes = df_result[abs(df_result["등락률(%)"]) > 30]
        if not invalid_changes.empty:
            errors.append("가격제한폭(±30%) 초과 종목 발견")

    # 5. 상태 메시지 반환
    if errors:
        status_message = "[경고] 오류 발생: " + ", ".join(errors)
        is_error = True
    else:
        status_message = f"[정상] {actual_count}/{expected_count} 수집, 결측 0건"
        is_error = False

    return status_message, is_error

# --- [실행부] 수집/검증 및 메일 발송 ---
if __name__ == "__main__":
    result_msg, has_error = collect_and_validate_stocks()
    print("=== 데이터 수집 및 검증 결과 ===")
    print(result_msg)

    # 메일 발송 설정 (환경 변수 이름 변경 반영)
    try:
        msg = MIMEMultipart()

        # 새 이름으로 읽기
        EMAIL_SENDER = os.environ.get("EMAIL_SENDER","")
        EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER","")
        EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg["Subject"] = f"주식 데이터 수집 검증 보고 - {result_msg}"

        body = (
            "안녕하세요, 오늘의 주식 크롤링 및 검증 결과입니다.\n\n"
            f"상태: {result_msg}\n\n"
            "새로운 종목 데이터가 정상적으로 갱신되었습니다."
        )
        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP_SSL("smtp.naver.com", 465)
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        server.quit()
        print("[메일 발송 성공] 갱신된 결과 메일이 전송되었습니다.")

    except Exception as e:
        print(f"[메일 발송 실패] 사유: {e}")

