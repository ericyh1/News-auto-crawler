import os
import pandas as pd
import requests
from lxml import html
from urllib.parse import urljoin

def main():
    GAS_URL = os.environ.get('GAS_URL')
    SHEET_ID = "1bFJhz4F5pj6Hanj4PoUQN-KTOETaUCbDE_RPPnZO1ec"
    # 請確保已將 Feeds_RealTime 工作表發佈為 CSV
    CONFIG_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"
    
    try:
        # 讀取設定檔，指定 header 所在行
        df_settings = pd.read_csv(CONFIG_URL)
    except Exception as e:
        print(f"讀取設定失敗: {e}")
        return

    all_results = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    for _, row in df_settings.iterrows():
        market = str(row.get('Market', '')).strip().upper()
        url = row.get('News Search')
        xpath_str = row.get('XPath')
        
        # 依照 Market 決定排除字欄位
        if market == 'TW':
            block_word = str(row.get('Block_tw', ''))
        elif market == 'HK':
            block_word = str(row.get('Block_hk', ''))
        else:
            block_word = ""

        if not url or pd.isna(url) or not xpath_str:
            continue
            
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            tree = html.fromstring(resp.content)
            elements = tree.xpath(xpath_str)
            
            market_results = []
            for el in elements:
                title = el.text_content().strip()
                link = el.get('href')
                if link and link.startswith('/'):
                    link = urljoin(url, link)
                
                # 排除邏輯：如果標題包含排除字則跳過
                if block_word and block_word != 'nan' and block_word in title:
                    continue
                
                if title and link:
                    market_results.append({'market': market, 'title': title, 'link': link})
            
            # 單一來源去重
            unique_market_results = list({v['title']:v for v in market_results}.values())
            all_results.extend(unique_market_results)
            
        except Exception as e:
            print(f"爬取錯誤 {url}: {e}")

    # 全部跑完後，再次針對全體資料過濾掉同樣標題的文章
    if all_results:
        final_data = list({v['title']:v for v in all_results}.values())
        
        # 傳送給 GAS
        try:
            post_resp = requests.post(GAS_URL, json={"data": final_data})
            print(f"GAS 回傳: {post_resp.text}")
        except Exception as e:
            print(f"傳送失敗: {e}")

if __name__ == "__main__":
    main()