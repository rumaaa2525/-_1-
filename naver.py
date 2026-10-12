import requests
from bs4 import BeautifulSoup

def get_naver_stock_list(group_code):
    """
    네이버 증권에서 특정 업종의 종목 리스트를 가져옵니다.
    group_code: 네이버 증권 URL에 포함된 업종 코드
    """
    url = f"https://stock.naver.com/market/stock/kr/industry/73?no=282"
    
    # 네이버는 가끔 인코딩 문제나 헤더 검사가 있으므로 header를 넣어주는 것이 좋습니다.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    response = requests.get(url, headers=headers)
    response.encoding = 'euc-kr'  # 네이버 금융은 euc-kr을 사용합니다.
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 종목 정보가 담긴 테이블을 찾습니다.
    # 네이버 금융 구조상 종목은 보통 'type_group' 클래스 내의 table에 있습니다.
    stock_list = []
    
    # 모든 종목 행(tr)을 찾습니다.
    rows = soup.select('table.type_group tr')
    
    for row in rows:
        # 종목명과 종목코드가 들어있는 태그를 추출합니다.
        # 보통 a 태그에 이름과 코드가 들어있습니다.
        name_tag = row.select_one('a')
        if name_tag:
            name = name_tag.text.strip()
            # 종목 코드는 보통 href 속성에 포함되어 있습니다 (예: code=005930)
            code_href = name_tag.get('href', '')
            if 'code=' in code_href:
                code = code_href.split('code=')[-1]
                stock_list.append({"name": name, "code": code})

    return stock_list

# --- 실행 부분 ---
# '전자장비와기기'의 groupCode를 확인해야 합니다. 
# (네이버 증권 페이지 URL에서 groupCode= 부분을 확인하세요)
# 예시 코드는 실제 작동을 위해 정확한 groupCode를 넣어야 합니다.
TARGET_GROUP_CODE = '282' # 여기에 실제 코드를 넣으세요.

stocks = get_naver_stock_list(TARGET_GROUP_CODE)

# 결과 출력 (사용자님 코드 형식과 동일)
print("stocks = [")
for s in stocks:
    print(f'    {s},')
print("]")
