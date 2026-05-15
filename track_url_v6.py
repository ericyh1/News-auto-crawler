import time
import random
import pandas as pd
from playwright.sync_api import sync_playwright
from lxml import html
from datetime import datetime, timezone
import os

# --- 1. 基礎工具函式 ---

def is_intermediate_domain(url):
    """ 
    判定是否為中間轉址網域。
    """
    if not url: return True
    url_lower = url.lower()
    blacklist = [
        "us.search.yahoo.com", "yahoo.com/rdlw", "r.search.yahoo.com",
        "affinity.net", "bizrate.com", "shophermedia.net", "provenpixel.com",
        "socialiqredir.com", "discounthero.org", "magik.ly", "netsourceio.com",
        "clickroll.net", "shopping123.com", "top-best.com",
        "v2i8b.com", "beyondcheap.com", "intentxredir.com",
        "peakoptions.site"
    ]
    return any(k in url_lower for k in blacklist)

def get_link_status(page, response):
    """
    新增功能：檢查網頁標題或內容是否包含失效關鍵字。
    包含關鍵字時回傳 "404"。
    """
    try:
        current_url = page.url
        if is_intermediate_domain(current_url): return "Error"
        if not response: return "No"

        # 取得網頁標題與 HTML 內容（轉小寫）
        page_title = page.title().lower()
        page_content = page.content().lower()
        
        # 定義 404 檢查關鍵字
        not_found_keywords = [
            "page not found", 
            "404", 
            "dead end", 
            "page cannot be found"
        ]
        
        # 條件檢查：標題或內容包含任一關鍵字
        if any(k in page_title for k in not_found_keywords) or \
           any(k in page_content for k in not_found_keywords):
            return "404"

        status = response.status
        # 處理某些網站的 Access Denied (403)，若標題無失效關鍵字則視為 Yes
        if status == 403 or "access denied" in page_title: return "Yes"
        if status >= 400: return "No"
        
        return "Yes" if 200 <= status < 300 else "No"
    except:
        return "No"

def safe_goto(page, url, wait_until="load", timeout=60000):
    try:
        return page.goto(url, wait_until=wait_until, timeout=timeout)
    except Exception as e:
        if "interrupted" in str(e):
            time.sleep(2)
            return None
        return None

def wait_for_redirect_smart(page, initial_url):
    try:
        resp = safe_goto(page, initial_url, wait_until="commit")
        for _ in range(8):
            if not is_intermediate_domain(page.url): return resp
            page.wait_for_timeout(4500)
            page.mouse.move(random.randint(100, 500), random.randint(100, 500))
        return resp
    except: return None

# --- 2. 核心抓取流程 ---

def run_retailer_capture(page, row, column_order):
    retailer = str(row.get('Retailer', 'N/A'))
    srp_url = str(row.get('SRP', ''))
    
    data = {col: ("N/A" if "Check" in col else "") for col in column_order}
    data["Retailer"], data["SRP"] = retailer, srp_url
    data["Update Date"] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    capture_status = {"Landing": False, "Cat1": False, "Cat2": False, "Cat3": False, "Cat4": False}

    for attempt in range(1, 6):
        needed = [k for k, v in capture_status.items() if v is False]
        if not needed: break
        
        try:
            safe_goto(page, srp_url, wait_until="load")
            time.sleep(3)
            tree = html.fromstring(page.content())
            
            dd_label = tree.xpath("//div[contains(@class,'TopNavCommerce')]//h3/a/@aria-label")
            if dd_label:
                data["DD Name"] = dd_label[0]
            else:
                data["DD Name"] = "DD cannot be found"
                break 

            # --- Landing Page 檢查 ---
            if not capture_status["Landing"]:
                raw_link = tree.xpath("//div[contains(@class,'compTitle')]/h3/a/@href")
                if raw_link:
                    resp = wait_for_redirect_smart(page, raw_link[0])
                    # 這裡會觸發新的 404 檢查
                    status = get_link_status(page, resp)
                    data["Link works"] = status
                    if not is_intermediate_domain(page.url):
                        data["Landing page URL"] = page.url
                        capture_status["Landing"] = True

            # --- Cat1 ~ Cat4 檢查 ---
            for i in range(1, 5):
                cat_key = f"Cat{i}"
                if not capture_status[cat_key]:
                    if page.url != srp_url: safe_goto(page, srp_url, wait_until="domcontentloaded")
                    c_tree = html.fromstring(page.content())
                    c_name = c_tree.xpath(f"//div[contains(@class,'TopNavCommerce')]/div[3]//li[{i}]//a//img/@alt")
                    c_link = c_tree.xpath(f"//div[contains(@class,'TopNavCommerce')]/div[3]//li[{i}]//a/@href")
                    
                    if c_name: data[f"{cat_key} Name"] = c_name[0]
                    else: data[f"{cat_key} Name"] = "N/A"

                    l_val = c_link[0] if c_link else ""
                    data[f"{cat_key} Link URL"] = l_val

                    if l_val and l_val not in ["", "#", "N/A"]:
                        c_resp = wait_for_redirect_smart(page, l_val)
                        if not is_intermediate_domain(page.url):
                            data[f"{cat_key} page URL"] = page.url
                            # 這裡也會觸發新的 404 檢查
                            data[f"{cat_key} Link works"] = get_link_status(page, c_resp)
                            if data[f"{cat_key} Name"] != "N/A":
                                capture_status[cat_key] = True
                    else:
                        data[f"{cat_key} Link works"] = "No"
                        capture_status[cat_key] = True 
        except: pass
    return data

# --- 3. 主程式執行 ---

def process_srp():
    input_file = 'urls.csv'
    output_file = 'srp_final_results.csv'
    column_order = [
        "Retailer", "SRP", "Update Date", "DD Name", "Landing page URL", "Link works", "Link Check",
        "Cat1 Name", "Cat1 Link URL", "Cat1 page URL", "Cat1 Link works", "Cat1 Link Check",
        "Cat2 Name", "Cat2 Link URL", "Cat2 page URL", "Cat2 Link works", "Cat2 Link Check",
        "Cat3 Name", "Cat3 Link URL", "Cat3 page URL", "Cat3 Link works", "Cat3 Link Check",
        "Cat4 Name", "Cat4 Link URL", "Cat4 page URL", "Cat4 Link works", "Cat4 Link Check"
    ]

    if not os.path.exists(input_file):
        print(f"❌ 找不到輸入檔案: {input_file}")
        return

    df_input = pd.read_csv(input_file)
    results_dict = {}

    with sync_playwright() as p:
        # 本機執行建議 headless=False 方便觀察關鍵字比對
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        page = context.new_page()

        for index, row in df_input.iterrows():
            print(f"🚀 [執行中] {index+1}/{len(df_input)}: {row['Retailer']}")
            results_dict[row['Retailer']] = run_retailer_capture(page, row, column_order)
            
            # 即時儲存，避免當機
            pd.DataFrame(list(results_dict.values()))[column_order].to_csv(output_file, index=False, encoding='utf-8-sig')

        # 補抓邏輯 (對 Cat Name N/A 的進行二次嘗試)
        for audit_round in range(1, 3):
            to_retry = [name for name, data in results_dict.items() 
                        if data["DD Name"] != "DD cannot be found" and 
                        any(data[f"Cat{i} Name"] == "N/A" for i in range(1, 5))]
            
            if not to_retry: break
            print(f"🔄 補抓第 {audit_round} 輪，剩餘 {len(to_retry)} 筆...")
            for name in to_retry:
                row = df_input[df_input['Retailer'] == name].iloc[0]
                results_dict[name] = run_retailer_capture(page, row, column_order)
                pd.DataFrame(list(results_dict.values()))[column_order].to_csv(output_file, index=False, encoding='utf-8-sig')

        browser.close()
        print(f"\n✅ 任務完成。結果已儲存至: {output_file}")

if __name__ == "__main__":
    process_srp()