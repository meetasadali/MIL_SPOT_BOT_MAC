import os
import sys
import threading
import time
from flask import Flask, jsonify, render_template, request, send_file
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- PyInstaller-compatible resource path ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS  # When using PyInstaller
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- Flask app with templates/static path set ---
app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static")
)

# --- Shared State ---
downloadable_file_content = ""
output_data = ""
script_running = False
pause_event = threading.Event()
captcha_event = threading.Event()
start_time = 0
completed_searches = 0
total_searches = 0

# --- Main Script Logic ---
def run_selenium_script(chromedriver_path, website_to_check, keywords, cities):
    global script_running, output_data, downloadable_file_content, completed_searches, total_searches
    script_running = True
    completed_searches = 0
    tab_counter = 0
    output_data = ""

    def log_message(msg):
        global output_data
        print(msg)
        output_data += msg + "\n"

    def init_driver():
        options = Options()
        options.add_argument("--incognito")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(service=Service(chromedriver_path), options=options)
        driver.set_window_size(1200, 800)
        wait = WebDriverWait(driver, 15)
        return driver, wait

    browser = {"driver": None, "wait": None}
    browser["driver"], browser["wait"] = init_driver()
    browser["driver"].get("https://www.google.com")

    def check_for_captcha(driver):
        try:
            if "captcha" in driver.current_url or "sorry" in driver.current_url or "unusual traffic" in driver.title.lower():
                captcha_event.set()
                return True
        except:
            return False
        return False

    def find_and_click_link(browser, website):
        nonlocal tab_counter
        driver = browser["driver"]
        wait = browser["wait"]

        try:
            results = wait.until(EC.presence_of_all_elements_located((By.XPATH, '//a[@href]')))
            for result in results:
                href = result.get_attribute("href")
                if href and website in href:
                    log_message(f"✅ Found and clicking: {href}")
                    wait.until(EC.element_to_be_clickable(result)).click()
                    time.sleep(2)

                    tab_counter += 1
                    if tab_counter >= 20:
                        driver.quit()
                        log_message("🌐 20 tabs opened. Restarting browser.")
                        browser["driver"], browser["wait"] = init_driver()
                        browser["driver"].get("https://www.google.com")
                        tab_counter = 0
                    else:
                        driver.execute_script("window.open('about:blank', '_blank');")
                        driver.switch_to.window(driver.window_handles[-1])
                        driver.get("https://www.google.com")
                    return True
        except Exception as e:
            log_message(f"⚠️ Retrying Link: {str(e)}")
        return False

    found_first = []
    found_second = []
    not_found = []

    for keyword in keywords:
        for city in cities:
            if not script_running:
                browser["driver"].quit()
                return

            if pause_event.is_set():
                log_message("⏸️ Script paused.")
                while pause_event.is_set():
                    time.sleep(1)

            search_term = f"{keyword} {city}"
            log_message(f"\n🔍 Searching: {search_term}")

            try:
                browser["driver"].get("https://www.google.com")
                box = browser["wait"].until(EC.presence_of_element_located((By.NAME, "q")))
                box.clear()
                box.send_keys(search_term)
                box.send_keys(Keys.RETURN)

                if check_for_captcha(browser["driver"]):
                    log_message("🤖 CAPTCHA detected. Waiting...")
                    captcha_event.wait()
                    captcha_event.clear()
                    log_message("✅ CAPTCHA solved. Retrying search...")

                    browser["driver"].get("https://www.google.com")
                    box = browser["wait"].until(EC.presence_of_element_located((By.NAME, "q")))
                    box.clear()
                    box.send_keys(search_term)
                    box.send_keys(Keys.RETURN)

                completed_searches += 1

                if find_and_click_link(browser, website_to_check):
                    found_first.append(search_term)
                    continue

                next_btn = browser["wait"].until(EC.element_to_be_clickable((By.ID, "pnnext")))
                browser["driver"].execute_script("arguments[0].scrollIntoView(true);", next_btn)
                next_btn.click()

                if find_and_click_link(browser, website_to_check):
                    found_second.append(search_term)
                else:
                    not_found.append(search_term)

            except Exception as e:
                log_message(f"❌ Error on {search_term}: {str(e)}")
                not_found.append(search_term)

    browser["driver"].quit()

    downloadable_file_content = "--- Page 1 ---\n" + "\n".join(found_first)
    downloadable_file_content += "\n\n--- Page 2 ---\n" + "\n".join(found_second)
    downloadable_file_content += "\n\n--- Not Found ---\n" + "\n".join(not_found)

    log_message("\n✅ Script completed.")
    script_running = False

# --- Flask Routes ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/run_script", methods=["POST"])
def run_script_route():
    global script_running, start_time, total_searches
    if script_running:
        return jsonify({"status": "error", "message": "Script is already running."})

    data = request.json
    chromedriver_path = data.get("chromedriver_path")
    website = data.get("website_to_check")
    keywords = [k.strip() for k in data.get("keywords", "").replace('\n', ',').split(',') if k.strip()]
    cities = [c.strip() for c in data.get("cities", "").replace('\n', ',').split(',') if c.strip()]

    total_searches = len(keywords) * len(cities)
    start_time = time.time()

    thread = threading.Thread(target=run_selenium_script, args=(chromedriver_path, website, keywords, cities))
    thread.start()

    return jsonify({"status": "success"})

@app.route("/pause", methods=["POST"])
def pause():
    pause_event.set()
    return jsonify({"status": "paused"})

@app.route("/resume", methods=["POST"])
def resume():
    pause_event.clear()
    return jsonify({"status": "resumed"})

@app.route("/captcha_solved", methods=["POST"])
def captcha_solved():
    captcha_event.set()
    captcha_event.clear()
    return jsonify({"status": "ok"})

@app.route("/stop", methods=["POST"])
def stop():
    global script_running
    script_running = False
    pause_event.clear()
    captcha_event.clear()
    return jsonify({"status": "stopped"})

@app.route("/status")
def status():
    elapsed = time.time() - start_time if start_time else 0
    return jsonify({
        "script_running": script_running,
        "captcha": captcha_event.is_set(),
        "paused": pause_event.is_set(),
        "elapsed_time": elapsed,
        "completed_searches": completed_searches,
        "total_searches": total_searches,
        "output": output_data,
        "results_content": downloadable_file_content if not script_running else ""
    })

@app.route("/download")
def download():
    if not downloadable_file_content:
        return "No results", 404
    return send_file(
        BytesIO(downloadable_file_content.encode("utf-8")),
        mimetype="text/plain",
        as_attachment=True,
        download_name="search_results.txt"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
