import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pandas as pd
import numpy as np
import requests

# ===================== 네이버 API 관련 설정 =====================
API = "https://m.stock.naver.com/api/stock"
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://m.stock.naver.com/",
})

def flatten_finance(code: str, freq: str, js: dict) -> list:
    fi = (js or {}).get("financeInfo", {})
    titles = {t.get("key"): t.get("title") for t in fi.get("trTitleList", [])}
    cons = {t.get("key"): t.get("isConsensus") for t in fi.get("trTitleList", [])}
    out = []
    for row in fi.get("rowList", []):
        for k, cell in (row.get("columns") or {}).items():
            out.append({"종목코드": code, "주기": freq, "기간": titles.get(k, k),
                        "컨센서스": cons.get(k), "항목": row.get("title"),
                        "값": (cell or {}).get("value")})
    return out


def collect_and_validate_stocks():
    # 1. 종목 리스트 정의
    stocks = [
        {"name": "삼성전기", "code": "009150"},
        {"name": "LG이노텍", "code": "011070"},
        {"name": "HT로보틱스", "code": "396300"},
        {"name": "대덕전자", "code": "353200"},
        {"name": "심텍", "code": "222800"},
        {"name": "롯데에너지머티리얼즈", "code": "020150"},
        {"name": "고영", "code": "098460"},
        {"name": "코리아써키트", "code": "007810"},
        {"name": "메가터치", "code": "446540"},
        {"name": "비에이치", "code": "090460"},
        {"name": "슈프리마", "code": "236200"},
        {"name": "태성", "code": "323280"},
        {"name": "한솔테크닉스", "code": "004710"},
        {"name": "광전자", "code": "017900"},
        {"name": "대주전자재료", "code": "078600"},
        {"name": "솔루엠", "code": "248070"},
    ]

    data_list = []
    fin_rows = []
    errors = []

    for item in stocks:
        name = item["name"]
        code = str(item["code"]).zfill(6)

        row = {"종목명": name, "종목코드": code}
        try:
            # 네이버 모바일 API 호출 (기본 정보 + 통합 정보 + 재무 정보)
            r_basic = SESSION.get(f"{API}/{code}/basic", timeout=15)
            r_integ = SESSION.get(f"{API}/{code}/integration", timeout=15)
            
            if r_basic.status_code != 200 or r_integ.status_code != 200:
                raise ValueError("네이버 API 응답 오류")

            basic = r_basic.json()
            integ = r_integ.json()

            # 기본 가격 및 등락 정보
            current_close = basic.get("closePrice")
            prev_close = basic.get("previousClosePrice")
            
            # 숫자형 변환 처리 (쉼표 제거 등)
            def clean_num(val):
                if val is None:
                    return None
                if isinstance(val, (int, float)):
                    return val
                try:
                    return float(str(val).replace(",", ""))
                except ValueError:
                    return None

            row["현재가(종가)"] = clean_num(current_close)
            row["전일대비"] = clean_num(basic.get("compareToPreviousClosePrice"))
            
            fluctuations_ratio = clean_num(basic.get("fluctuationsRatio"))
            row["등락률(%)"] = fluctuations_ratio
            row["상승여부"] = fluctuations_ratio > 0 if fluctuations_ratio is not None else None

            # 통합 정보(totalInfos)에서 시가, 고가, 저가, 거래량, 시가총액, PER, PBR, 외국인비율 등 일괄 추출
            for it in integ.get("totalInfos", []):
                key = it.get("key")
                val = it.get("value")
                # 보기 편한 주요 키 매칭 및 저장
                if key in ["openPrice", "시가"]:
                    row["시가"] = clean_num(val)
                elif key in ["highPrice", "고가"]:
                    row["고가"] = clean_num(val)
                elif key in ["lowPrice", "저가"]:
                    row["저가"] = clean_num(val)
                elif key in ["accumulatedTradingVolume", "거래량"]:
                    row["거래량"] = clean_num(val)
                elif key in ["accumulatedTradingValue", "거래대금"]:
                    row["거래대금"] = clean_num(val)
                elif key in ["marketCapitalization", "시가총액"]:
                    row["시가총액"] = val  # 원본 문자열 또는 숫자 유지
                elif key in ["foreignRatio", "외국인비율"]:
                    row["외국인비율"] = val
                
                # 그 외 모든 지표도 동적으로 담기
                row[key] = val

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
        # 등락률 기준으로 상하한가(±30%) 초과 검증
        valid_df = df_result[df_result["등락률(%)"].notna()]
        if not valid_df.empty:
            invalid_changes = valid_df[abs(valid_df["등락률(%)"]) > 30]
            if not invalid_changes.empty:
                errors.append("가격제한폭(±30%) 초과 종목 발견")

    # 6. 상태 메시지 반환
    if errors:
        status_message = "[경고] 오류 발생: " + ", ".join(errors)
        is_error = True
    else:
        status_message = f"[정상] {actual_count}/{expected_count} 종목 상세 지표 수집 완료"
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
        msg["Subject"] = f"주식 상세 데이터 수집 및 검증 보고 - {result_msg}"

        body = (
            "안녕하세요, 오늘의 주식 확장 지표 크롤링 및 검증 결과입니다.\n\n"
            f"상태: {result_msg}\n\n"
            "시가총액, 외국인비율 및 상세 지표가 포함된 CSV 파일을 첨부합니다."
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
