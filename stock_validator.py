import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import FinanceDataReader as fdr
import pandas as pd


def collect_and_validate_stocks():
    # 1. 종목 리스트
    stocks = [
        {"name": "삼성전기", "code": "009150"},
        {"name": "LG이노텍", "code": "011070"},
        {"name": "HT로보틱스", "code": "396300"},
        {"name": "대덕전자", "code": "353200"},
        {"name": "심텍", "code": "222800"},
        {"name": "롯데에너지머티리얼즈", "code": "020150"},
    ]

    data_list = []
    errors = []

    # 2. 데이터 수집
    for item in stocks:
        name = item["name"]
        code = str(item["code"]).zfill(6)

        try:
            df = fdr.DataReader(code, "2026-01-01")

            if len(df) < 2:
                raise ValueError("등락률 계산에 필요한 데이터가 2일 미만입니다.")

            latest_day = df.iloc[-1]
            prev_day = df.iloc[-2]

            current_close = latest_day["Close"]
            previous_close = prev_day["Close"]

            if pd.isna(current_close) or pd.isna(previous_close):
                raise ValueError("종가에 결측치가 있습니다.")

            if previous_close == 0:
                raise ValueError("이전 종가가 0이라 등락률을 계산할 수 없습니다.")

            price = int(current_close)
            change = round(
                ((current_close - previous_close) / previous_close) * 100,
                2,
            )

            data_list.append({
                "종목명": name,
                "종목코드": code,
                "현재가": price,
                "등락률(%)": change,
                "상승여부": change > 0,
            })

        except Exception as e:
            errors.append(f"{name}({code}) 수집 실패: {e}")

    # 3. CSV 파일 생성
    columns = [
        "종목명",
        "종목코드",
        "현재가",
        "등락률(%)",
        "상승여부",
    ]
    df_result = pd.DataFrame(data_list, columns=columns)

    df_result.to_csv(
        "electronic_equipment_multi.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 4. 검증
    expected_count = len(stocks)
    actual_count = len(df_result)

    if actual_count != expected_count:
        errors.append(
            f"수집 건수 불일치: 기대({expected_count}) != 실제({actual_count})"
        )

    missing_count = int(df_result.isnull().sum().sum())
    if missing_count > 0:
        errors.append(f"결측치 발견: {missing_count}건")

    if not df_result.empty:
        invalid_changes = df_result[
            df_result["등락률(%)"].abs() > 30
        ]
        if not invalid_changes.empty:
            errors.append("가격제한폭(±30%) 초과 종목 발견")

    # 5. 상태 메시지
    if errors:
        status_message = "[경고] 오류 발생: " + ", ".join(errors)
        is_error = True
    else:
        status_message = (
            f"[정상] {actual_count}/{expected_count} 수집, 결측 0건"
        )
        is_error = False

    return status_message, is_error


if __name__ == "__main__":
    result_msg, has_error = collect_and_validate_stocks()

    print("=== 데이터 수집 및 검증 결과 ===")
    print(result_msg)

    # 메일 발송
    try:
        EMAIL_SENDER = os.environ.get("MY_EMAIL_SENDER", "").strip()
        EMAIL_RECEIVER = os.environ.get("MY_EMAIL_RECEIVER", "").strip()
        EMAIL_PASSWORD = os.environ.get("MY_EMAIL_PW", "").strip()

        # 환경변수 누락 확인 — 비밀번호 값은 출력하지 않습니다.
        missing_settings = [
            name
            for name, value in [
                ("MY_EMAIL_SENDER", EMAIL_SENDER),
                ("MY_EMAIL_RECEIVER", EMAIL_RECEIVER),
                ("MY_EMAIL_PW", EMAIL_PASSWORD),
            ]
            if not value
        ]

        if missing_settings:
            raise ValueError(
                "메일 설정 누락: " + ", ".join(missing_settings)
            )

        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg["Subject"] = f"주식 데이터 수집 검증 보고 - {result_msg}"

        if has_error:
            update_message = "일부 데이터 수집 또는 검증에 문제가 있습니다."
        else:
            update_message = "종목 데이터가 정상적으로 갱신되었습니다."

        body = (
            "안녕하세요, 오늘의 주식 크롤링 및 검증 결과입니다.\n\n"
            f"상태: {result_msg}\n\n"
            f"{update_message}"
        )
        msg.attach(MIMEText(body, "plain", "utf-8"))

        print("[메일] 네이버 SMTP 서버에 연결합니다.")

        with smtplib.SMTP_SSL(
            "smtp.naver.com",
            465,
            timeout=30,
        ) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            print("[메일] 로그인 성공")

            refused = server.sendmail(
                EMAIL_SENDER,
                [EMAIL_RECEIVER],
                msg.as_string(),
            )

            if refused:
                raise RuntimeError("수신 주소가 서버에서 거부되었습니다.")

        print("[메일 발송 성공] 서버가 메일 발송 요청을 수락했습니다.")

    except Exception as e:
        print(f"[메일 발송 실패] 사유: {e}")
        raise
