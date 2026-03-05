#!/usr/bin/env python3
"""
TiffinBillSender – WhatsApp PDF auto-sender via Selenium.
Reconstructed and fixed: updated WhatsApp Web selectors (2025-2026).
"""

import os
import re
import time
import json
import shutil
import logging
import urllib.parse as urllib
import platform
from datetime import datetime, timedelta
import sys

# ---------------------------------------------------------------------------
# exe_dir handling (so frozen .exe can find config/ next to itself)
# ---------------------------------------------------------------------------
exe_dir = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)
if exe_dir not in sys.path:
    sys.path.insert(0, exe_dir)

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
)

from config.settings import *

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
os.makedirs("./output", exist_ok=True)
os.makedirs("./logs", exist_ok=True)
logging.basicConfig(
    filename=os.path.join("./logs", "wa_auto_send_brave.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def log_step(step, **kv):
    msg = f"STEP={step}"
    for k, v in kv.items():
        msg += f" | {k}={v}"
    logging.info(msg)


def last_month_label():
    today = datetime.now()
    first = today.replace(day=1)
    last_month_last_day = first - timedelta(days=1)
    return last_month_last_day.strftime("%B %Y")


def render_message():
    return MESSAGE_TEMPLATE.replace("{MONTH}", last_month_label())


# ---------------------------------------------------------------------------
# Browser binary detection
# ---------------------------------------------------------------------------
def find_chrome_binary(user_hint=None):
    if user_hint and os.path.exists(user_hint):
        return user_hint
    env = os.environ.get("CHROME_PATH", "").strip()
    if env and os.path.exists(env):
        return env
    system = platform.system().lower()
    candidates = []
    if system == "windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    elif system == "darwin":
        candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]
        for name in ("google-chrome", "chrome", "chromium", "chromium-browser"):
            p = shutil.which(name)
            if p:
                candidates.insert(0, p)
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def find_brave_binary(user_hint=None):
    if user_hint and os.path.exists(user_hint):
        return user_hint
    env = os.environ.get("BRAVE_PATH", "").strip()
    if env and os.path.exists(env):
        return env
    system = platform.system().lower()
    candidates = []
    if system == "windows":
        candidates = [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        ]
    elif system == "darwin":
        candidates = ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]
    else:
        candidates = [
            "/usr/bin/brave-browser",
            "/usr/bin/brave-browser-stable",
            "/snap/bin/brave",
        ]
        for name in ("brave-browser", "brave-browser-stable", "brave"):
            p = shutil.which(name)
            if p:
                candidates.insert(0, p)
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


# ---------------------------------------------------------------------------
# Phone extraction from filename
# ---------------------------------------------------------------------------
def extract_phone_from_filename(filename, default_cc="91"):
    base = os.path.basename(filename)
    # normalise separators
    base = base.replace("_", " ").replace("-", " ").replace(".", " ")
    base = re.sub(r"[()]", " ", base)

    # try +91 pattern first
    m = re.search(r"\+91[\s]*([0-9][\s0-9]{9,})", base)
    if m:
        digits = re.sub(r"\D", "", m.group(0))
        return "+" + digits[-12:]

    # 10-12 digit block
    digits = re.sub(r"\D", "", base)
    if len(digits) >= 12:
        return "+" + digits[-12:]

    if digits.startswith("91") and len(digits) >= 12:
        return "+" + digits[-12:]

    # try 91XXXXXXXXXX pattern
    m = re.search(r"\b91[\s-]*([0-9][\s0-9]{9,})\b", base)
    if m:
        digits = re.sub(r"\D", "", m.group(0))
        return "+" + digits[-12:]

    # fall back to longest digit block
    if len(digits) >= 10:
        phone = digits[-10:]
        return f"+{default_cc}{phone}"

    return None


# ---------------------------------------------------------------------------
# PDF scanning
# ---------------------------------------------------------------------------
def scan_pdfs_top_level(pdf_dir):
    pdfs = []
    try:
        for f in sorted(os.listdir(pdf_dir)):
            if f.lower().endswith(".pdf"):
                pdfs.append(os.path.join(pdf_dir, f))
    except Exception:
        pass
    return pdfs


# ---------------------------------------------------------------------------
# File move helpers
# ---------------------------------------------------------------------------
def move_to_sent(pdf_path):
    try:
        sent_dir = os.path.join(PDF_DIR, SENT_DIR_NAME)
        os.makedirs(sent_dir, exist_ok=True)
        base = os.path.basename(pdf_path)
        name, ext = os.path.splitext(base)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(sent_dir, f"{name}__sent_{ts}{ext}")
        shutil.move(pdf_path, dest)
        log_step("PDF_MOVED_TO_SENT", dest=os.path.relpath(dest))
    except Exception:
        logging.error("Failed to move PDF to sent folder", exc_info=True)


def move_to_not_sent(pdf_path):
    try:
        not_sent_dir = os.path.join(PDF_DIR, "not_sent")
        os.makedirs(not_sent_dir, exist_ok=True)
        base = os.path.basename(pdf_path)
        dest = os.path.join(not_sent_dir, base)
        if os.path.exists(dest):
            name, ext = os.path.splitext(base)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(not_sent_dir, f"{name}__failed_{ts}{ext}")
        shutil.move(pdf_path, dest)
        log_step("PDF_MOVED_TO_NOT_SENT", dest=os.path.relpath(dest))
    except Exception:
        logging.error("Failed to move PDF to not_sent folder", exc_info=True)


# ---------------------------------------------------------------------------
# Driver setup
# ---------------------------------------------------------------------------
def setup_driver():
    opts = ChromeOptions()
    browser = (BROWSER or "chrome").lower().strip()

    if browser == "chrome":
        chrome_binary = find_chrome_binary(CHROME_PATH)
        if chrome_binary:
            opts.binary_location = chrome_binary
        profile_dir = "./chrome_profile"
    elif browser == "brave":
        brave_binary = find_brave_binary(BRAVE_PATH)
        if not brave_binary:
            raise RuntimeError(
                "Brave browser not found. Set BRAVE_PATH or install Brave."
            )
        opts.binary_location = brave_binary
        profile_dir = "./brave_profile"
    else:
        raise RuntimeError("BROWSER must be 'chrome' or 'brave' in config/settings.py")

    os.makedirs(profile_dir, exist_ok=True)
    opts.add_argument(f"--user-data-dir={os.path.abspath(profile_dir)}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--lang=en-US")
    opts.add_argument("--start-maximized")
    opts.page_load_strategy = "eager"

    if HEADLESS:
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1366,768")

    try:
        if CHROMEDRIVER_PATH and os.path.exists(CHROMEDRIVER_PATH):
            service = Service(CHROMEDRIVER_PATH)
            driver = webdriver.Chrome(service=service, options=opts)
        else:
            driver = webdriver.Chrome(options=opts)
    except Exception:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)

    driver.set_page_load_timeout(CHAT_READY_TIMEOUT)
    return driver


# ---------------------------------------------------------------------------
# Login helpers
# ---------------------------------------------------------------------------
def is_logged_in_ui(driver):
    sels = (
        "div[role='grid']",
        "div[aria-label='Chat list']",
        "#side",
        "#main",
    )
    try:
        return any(driver.find_elements(By.CSS_SELECTOR, s) for s in sels)
    except Exception:
        return False


def _qr_visible(driver):
    sels = (
        "canvas[aria-label='Scan me!']",
        "div[data-testid='qrcode']",
        "div[data-testid^='qrcode']",
        "img[alt='Scan me!']",
        "div[data-ref] canvas",
    )
    try:
        return any(driver.find_elements(By.CSS_SELECTOR, s) for s in sels)
    except Exception:
        return False


def ensure_logged_in(driver, max_wait_seconds=900):
    driver.get("https://web.whatsapp.com")
    try:
        WebDriverWait(driver, max_wait_seconds).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                "div[role='grid'], div[aria-label='Chat list'], #side, #main"))
        )
        log_step("LOGGED_IN")
    except TimeoutException:
        log_step("LOGIN_TIMEOUT")


# ---------------------------------------------------------------------------
# Chat navigation
# ---------------------------------------------------------------------------
def open_chat(driver, phone_e164):
    url = f"https://web.whatsapp.com/send?phone={phone_e164.replace('+', '')}"
    driver.get(url)
    try:
        WebDriverWait(driver, CHAT_READY_TIMEOUT).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#main div[role='textbox'][contenteditable='true']")
            )
        )
        log_step("CHAT_OPENED", phone=phone_e164)
        return True
    except TimeoutException:
        log_step("CHAT_OPEN_FAILED", phone=phone_e164)
        return False


# ===================================================================
# ATTACHMENT FLOW  (v6 — simplified, based on wa-automation approach)
# ===================================================================

# --- Attach button selectors (2025-2026 WhatsApp Web) ---
ATTACH_BTN_SELECTORS = [
    (By.CSS_SELECTOR, "div[data-tab='6']"),          # Confirmed working
    (By.CSS_SELECTOR, "span[data-icon='plus']"),
    (By.CSS_SELECTOR, "span[data-icon='clip']"),
    (By.CSS_SELECTOR, "[data-testid='conversation-clip']"),
    (By.CSS_SELECTOR, "button[title='Attach']"),
    (By.XPATH, "//span[@data-icon='plus']"),
    (By.XPATH, "//span[@data-icon='clip']"),
    (By.XPATH, "//div[@title='Attach']"),
]

# --- Document file input selectors (the hidden input with accept='*') ---
DOC_INPUT_SELECTORS = [
    (By.CSS_SELECTOR, "input[type='file'][accept='*']"),
    (By.CSS_SELECTOR, "input[type='file']:not([accept*='image']):not([accept*='video'])"),
    (By.CSS_SELECTOR, "input[type='file'][accept='*/*']"),
    (By.CSS_SELECTOR, "input[type='file']"),  # Last resort: any file input
]

SEND_BTN_SELECTORS = [
    "span[data-icon='send']",
    "div[role='button'][aria-label='Send']",
    "button[aria-label='Send']",
    "[data-testid='send']",
    "span[data-testid='send']",
]


def _save_debug_screenshot(driver, label="debug"):
    """Save a screenshot + DOM dump for debugging when things fail."""
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ss_path = os.path.join("./logs", f"screenshot_{label}_{ts}.png")
        driver.save_screenshot(ss_path)
        log_step("DEBUG_SCREENSHOT_SAVED", path=ss_path)
    except Exception:
        log_step("DEBUG_SCREENSHOT_FAILED")

    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dom_path = os.path.join("./logs", f"dom_dump_{label}_{ts}.txt")
        dom_info = driver.execute_script("""
            var result = '';
            var inputs = document.querySelectorAll('input[type="file"]');
            result += '=== FILE INPUTS (' + inputs.length + ') ===\\n';
            for (var i = 0; i < inputs.length; i++) {
                result += 'INPUT[' + i + ']: accept=' + (inputs[i].accept||'NONE')
                    + ' display=' + getComputedStyle(inputs[i]).display
                    + ' parent=' + (inputs[i].parentElement ? inputs[i].parentElement.tagName + '.' + (inputs[i].parentElement.className||'').substring(0,60) : 'NONE')
                    + '\\n';
            }
            var icons = document.querySelectorAll('[data-icon]');
            result += '\\n=== DATA-ICON (' + icons.length + ') ===\\n';
            for (var i = 0; i < icons.length; i++) {
                result += icons[i].tagName + ' icon=' + icons[i].getAttribute('data-icon') + '\\n';
            }
            var tabs = document.querySelectorAll('[data-tab]');
            result += '\\n=== DATA-TAB (' + tabs.length + ') ===\\n';
            for (var i = 0; i < tabs.length; i++) {
                result += tabs[i].tagName + ' tab=' + tabs[i].getAttribute('data-tab')
                    + ' aria=' + (tabs[i].getAttribute('aria-label')||'') + '\\n';
            }
            var testids = document.querySelectorAll('[data-testid]');
            result += '\\n=== DATA-TESTID (' + testids.length + ') ===\\n';
            for (var i = 0; i < testids.length; i++) {
                var t = testids[i].getAttribute('data-testid');
                if (t.indexOf('attach') >= 0 || t.indexOf('clip') >= 0 || t.indexOf('send') >= 0 || t.indexOf('doc') >= 0 || t.indexOf('file') >= 0) {
                    result += testids[i].tagName + ' testid=' + t + '\\n';
                }
            }
            return result;
        """)
        with open(dom_path, "w", encoding="utf-8") as f:
            f.write(dom_info)
        log_step("DOM_DUMP_SAVED", path=dom_path)
    except Exception as e:
        log_step("DOM_DUMP_FAILED", error=str(e))


def _click_attach_button(driver):
    """Click the '+' / paperclip attach button. Returns True on success."""
    for by, sel in ATTACH_BTN_SELECTORS:
        try:
            btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((by, sel))
            )
            btn.click()
            log_step("ATTACH_BTN_CLICKED", selector=sel)
            return True
        except Exception:
            continue
    log_step("ATTACH_BTN_NOT_FOUND")
    return False


def _find_document_input(driver, timeout=10):
    """
    Wait for and find the document file input element.
    Uses WebDriverWait (presence_of, not clickable) since file inputs are hidden.
    """
    for by, sel in DOC_INPUT_SELECTORS:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, sel))
            )
            acc = el.get_attribute("accept") or ""
            log_step("DOC_INPUT_FOUND", selector=sel, accept=acc)
            return el
        except Exception:
            continue
    return None


def _make_input_usable(driver, el):
    """Make a hidden file input usable by Selenium."""
    try:
        driver.execute_script("""
            var el = arguments[0];
            el.style.display = 'block';
            el.style.visibility = 'visible';
            el.style.opacity = '1';
            el.style.width = '1px';
            el.style.height = '1px';
            el.style.position = 'absolute';
            el.removeAttribute('hidden');
            el.removeAttribute('disabled');
        """, el)
    except Exception:
        pass


def wait_for_preview_ready(driver):
    """Wait for the file-preview screen (caption box + send button)."""
    cap = None
    try:
        cap = WebDriverWait(driver, 15, poll_frequency=PREVIEW_POLL_SECONDS).until(
            EC.visibility_of_element_located((
                By.CSS_SELECTOR,
                "div[aria-placeholder='Add a caption'][contenteditable='true'], "
                "div[contenteditable='true'][data-lexical-editor='true'], "
                "div[contenteditable='true'][data-tab='undefined']",
            ))
        )
        log_step("PREVIEW_CAPTION_VISIBLE")
    except TimeoutException:
        pass

    # Try multiple send button selectors
    send_sels = [
        "div[role='button'][aria-label='Send']",
        "span[data-icon='send']",
        "[data-testid='send']",
        "button[aria-label='Send']",
    ]
    for sel in send_sels:
        try:
            btn = WebDriverWait(
                driver, PREVIEW_READY_TIMEOUT, poll_frequency=PREVIEW_POLL_SECONDS
            ).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, sel))
            )
            log_step("PREVIEW_SEND_BTN_VISIBLE", selector=sel)
            time.sleep(PREVIEW_PAUSE_SEC)
            return cap, btn
        except TimeoutException:
            continue

    return cap, None


def focus_caption_box(driver):
    """Make sure the caption box in the preview screen is focused."""
    sels = [
        "div[aria-placeholder='Add a caption'][contenteditable='true']",
        "div[contenteditable='true'][data-lexical-editor='true']",
        "div[contenteditable='true'][data-tab='undefined']",
    ]
    for sel in sels:
        try:
            el = WebDriverWait(
                driver, 5, poll_frequency=PREVIEW_POLL_SECONDS
            ).until(EC.visibility_of_element_located((By.CSS_SELECTOR, sel)))
            el.click()
            driver.execute_script("arguments[0].focus()", el)
            return el
        except Exception:
            continue
    return None


def click_send_button(driver):
    """Click the Send button (works for both preview screen and chat)."""
    for sel in SEND_BTN_SELECTORS:
        try:
            btn = WebDriverWait(
                driver, SEND_ATTEMPT_TIMEOUT, poll_frequency=PREVIEW_POLL_SECONDS
            ).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
            btn.click()
            log_step("SEND_BTN_CLICKED", selector=sel)
            return True
        except ElementClickInterceptedException:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
                driver.execute_script("arguments[0].click();", btn)
                log_step("SEND_BTN_JS_CLICK", selector=sel)
                return True
            except Exception:
                continue
        except Exception:
            continue
    log_step("SEND_BTN_FAILED")
    return False


def _wait_upload_complete(driver, timeout=120):
    """Wait until WhatsApp finishes uploading the file (spinning icon disappears)."""
    try:
        # Wait for upload spinner to appear then disappear
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "svg.x9tu13d.x1bndym7"))
        )
        WebDriverWait(driver, timeout).until_not(
            EC.presence_of_element_located((By.CSS_SELECTOR, "svg.x9tu13d.x1bndym7"))
        )
    except TimeoutException:
        pass


# ===================================================================
#  MAIN ATTACH + SEND  (v6 — simplified proven approach)
#
#  Based on working wa-automation library approach:
#  1. Click attach button (div[data-tab='6'])
#  2. Wait for file inputs to appear
#  3. Find input[type='file'][accept='*'] directly (NO Document click needed!)
#  4. send_keys() the file path
#  5. Wait for preview → send
# ===================================================================
def attach_document_with_caption_and_send(driver, pdf_path, caption_text):
    abs_path = os.path.abspath(pdf_path)
    log_step("ATTACH_START", file=os.path.basename(pdf_path))

    # === STEP 1: Click the attach button ===
    ok = _click_attach_button(driver)
    if not ok:
        _save_debug_screenshot(driver, "no_attach_btn")
        return False

    # === STEP 2: Wait for file input to appear, then send file ===
    # After clicking "+", WhatsApp adds hidden file inputs to the DOM.
    # The document input has accept='*'. We find it directly — NO need to
    # click "Document" menu item (this is the key fix!).
    time.sleep(1)  # Let the menu render and inputs appear

    doc_input = _find_document_input(driver, timeout=10)

    if not doc_input:
        # Retry: close menu and try again
        log_step("DOC_INPUT_NOT_FOUND_RETRYING")
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.5)
        except Exception:
            pass
        _click_attach_button(driver)
        time.sleep(2)  # Wait longer this time
        doc_input = _find_document_input(driver, timeout=15)

    if not doc_input:
        log_step("DOC_INPUT_NOT_FOUND_FINAL")
        _save_debug_screenshot(driver, "no_doc_input")
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass
        return False

    # === STEP 3: Make input usable and send file path ===
    _make_input_usable(driver, doc_input)

    try:
        doc_input.send_keys(abs_path)
        log_step("FILE_SENT_TO_INPUT", path=os.path.basename(pdf_path))
    except Exception as e:
        log_step("FILE_SEND_FAILED", error=str(e))
        _save_debug_screenshot(driver, "send_keys_failed")
        return False

    # === STEP 4: Wait for preview screen ===
    time.sleep(2)
    cap, btn = wait_for_preview_ready(driver)
    if btn is None:
        log_step("PREVIEW_NOT_READY")
        _save_debug_screenshot(driver, "no_preview")
        return False

    # === STEP 5: Type caption if needed ===
    if caption_text:
        cap_el = cap or focus_caption_box(driver)
        if cap_el:
            try:
                time.sleep(FOCUS_PAUSE_SEC)
                driver.execute_script(
                    "arguments[0].focus(); "
                    "arguments[0].innerHTML = ''; "
                    "arguments[0].innerHTML = arguments[1]; "
                    "arguments[0].dispatchEvent(new InputEvent('input', "
                    "{ bubbles: true, cancelable: true, inputType: 'insertText', data: arguments[1] }));",
                    cap_el, caption_text
                )
                log_step("CAPTION_TYPED")
            except Exception:
                log_step("CAPTION_TYPE_FAILED")

    # === STEP 6: Click send ===
    sent = click_send_button(driver)
    if not sent:
        log_step("SEND_FAILED")
        return False

    # === STEP 7: Wait for upload to complete ===
    _wait_upload_complete(driver)
    time.sleep(POST_SEND_ATTACHMENT_PAUSE_SEC)
    log_step("ATTACH_COMPLETE", file=os.path.basename(pdf_path))
    return True


# ---------------------------------------------------------------------------
# Text insertion helpers
# ---------------------------------------------------------------------------
def insert_full_text_via_js(driver, composer, text):
    script = """
    const el = arguments[0];
    const txt = arguments[1];
    try {
      el.focus();
      const sel = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(el);
      sel.removeAllRanges();
      sel.addRange(range);
      document.execCommand('insertText', false, txt);
      return true;
    } catch(e) {
      try { el.textContent = txt; return true; } catch(e2) { return false; }
    }
    """
    try:
        ok = driver.execute_script(script, composer, text)
        return bool(ok)
    except Exception:
        return False


def build_prefill_text_url(phone_e164, text):
    number = phone_e164.replace("+", "")
    q = urllib.parse.urlencode({"text": text})
    return f"https://web.whatsapp.com/send?phone={number}&{q}"


# ---------------------------------------------------------------------------
# Text message sending
# ---------------------------------------------------------------------------
def _ensure_composer_in_main(driver):
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.1)
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    except Exception:
        pass

    composer = WebDriverWait(driver, CHAT_READY_TIMEOUT).until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "#main div[role='textbox'][contenteditable='true']")
        )
    )

    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", composer
        )
    except Exception:
        pass

    try:
        composer.click()
    except ElementNotInteractableException:
        try:
            ActionChains(driver).move_to_element(composer).click().perform()
        except Exception:
            pass

    try:
        driver.execute_script("arguments[0].focus()", composer)
    except Exception:
        pass

    return composer


def send_text_message_fast(driver, text):
    try:
        composer = WebDriverWait(driver, CHAT_READY_TIMEOUT).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, "#main div[role='textbox'][contenteditable='true']")
            )
        )
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", composer
        )
        composer.click()
        driver.execute_script("arguments[0].focus()", composer)

        # Select-all + delete to clear
        ActionChains(driver).key_down(Keys.CONTROL).send_keys("a").key_up(
            Keys.CONTROL
        ).send_keys(Keys.BACK_SPACE).perform()

        lines = text.strip().splitlines()
        for i, line in enumerate(lines):
            if line:
                composer.send_keys(line)
            if i < len(lines) - 1:
                ActionChains(driver).key_down(Keys.SHIFT).send_keys(
                    Keys.ENTER
                ).key_up(Keys.SHIFT).perform()
                time.sleep(0.05)

        composer.send_keys(Keys.ENTER)
        log_step("TEXT_SENT_FAST")
        time.sleep(0.4)
        return True
    except Exception:
        logging.error("send_text_message_fast failed", exc_info=True)
        return False


def _click_chat_send_button(driver):
    try:
        btn = WebDriverWait(
            driver, SEND_ATTEMPT_TIMEOUT, poll_frequency=PREVIEW_POLL_SECONDS
        ).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "#main div[role='button'][aria-label='Send']")
            )
        )
        btn.click()
        log_step("TEXT_SEND_BTN_CLICKED")
        return True
    except ElementClickInterceptedException:
        try:
            btn = driver.find_element(
                By.CSS_SELECTOR, "#main div[role='button'][aria-label='Send']"
            )
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", btn
            )
            driver.execute_script("arguments[0].click();", btn)
            log_step("TEXT_SEND_JS_CLICK")
            return True
        except Exception:
            logging.error("Send button click failed in chat", exc_info=True)
            return False
    except Exception:
        logging.error("Send button not clickable in chat", exc_info=True)
        return False


def _wait_message_dispatched(driver, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        try:
            composer = driver.find_element(
                By.CSS_SELECTOR,
                "#main div[role='textbox'][contenteditable='true']",
            )
            text_now = composer.text.strip()
            try:
                btn = driver.find_element(
                    By.CSS_SELECTOR,
                    "#main div[role='button'][aria-label='Send']",
                )
                disabled = btn.get_attribute("aria-disabled") == "true"
            except Exception:
                disabled = True
            if text_now == "" or disabled:
                return True
        except Exception:
            return True
        time.sleep(0.25)
    return True


def send_text_message(driver, phone_e164, text):
    try:
        url = build_prefill_text_url(phone_e164, text)
        driver.get(url)
        log_step("TEXT_NAV_WITH_PREFILL", phone=phone_e164)

        composer = _ensure_composer_in_main(driver)

        if not composer.text.strip():
            try:
                ok = insert_full_text_via_js(driver, composer, text)
                if not ok:
                    composer.send_keys(text)
                log_step("TEXT_TYPED_FALLBACK")
            except Exception:
                pass

        ok = _click_chat_send_button(driver)
        if not ok:
            try:
                composer.send_keys(Keys.ENTER)
                log_step("TEXT_ENTER_SENT_FALLBACK")
            except Exception:
                log_step("TEXT_SEND_FAILED_FALLBACK")
                return False

        _wait_message_dispatched(driver, timeout=8)
        log_step("TEXT_SENT_CONFIRMED")
        time.sleep(0.6)
        return True
    except Exception:
        logging.error("Failed to send text after attachment", exc_info=True)
        return False


# ===================================================================
#  MAIN
# ===================================================================
def main():
    logging.info(
        f"Headless={HEADLESS} | Browser={BROWSER} | PDF_DIR={PDF_DIR}"
    )
    message_text = render_message()
    pdfs_all = scan_pdfs_top_level(PDF_DIR)

    if not pdfs_all:
        print(
            "No PDFs found in ./pdfs_folder. Put your invoices there and run again.\n"
        )
        logging.info("No PDFs to process")
        input("Press Enter to close...")
        return

    pdfs = pdfs_all[: max(1, int(BATCH_SIZE))]
    driver = setup_driver()

    try:
        ensure_logged_in(driver, max_wait_seconds=LONG_LOGIN_WAIT_SEC)
    except Exception:
        pass

    success = 0
    failed = 0

    for pdf in pdfs:
        # Re-check login
        if not is_logged_in_ui(driver):
            ensure_logged_in(driver, max_wait_seconds=LONG_LOGIN_WAIT_SEC)

        phone = extract_phone_from_filename(pdf, COUNTRY_CODE)
        if not phone:
            log_step("SKIP_NO_PHONE_IN_NAME", file=os.path.basename(pdf))
            move_to_not_sent(pdf)
            failed += 1
            continue

        ok_chat = open_chat(driver, phone)
        if not ok_chat:
            print(
                f"Chat did not load for {phone} within {CHAT_READY_TIMEOUT}"
                " seconds. Exiting."
            )
            logging.error(f"EXIT_EARLY_CHAT_NOT_LOADED phone={phone}")
            try:
                driver.quit()
            except Exception:
                pass
            sys.exit(2)

        started = time.time()

        if not attach_document_with_caption_and_send(driver, pdf, DOCUMENT_CAPTION):
            failed += 1
            log_step(
                "FAIL_ATTACH_OR_SEND",
                phone=phone,
                file=os.path.basename(pdf),
            )
            move_to_not_sent(pdf)
            continue

        if (time.time() - started) > PER_DOC_TIMEOUT:
            failed += 1
            log_step(
                "PER_DOC_TIMEOUT_AFTER_SEND",
                phone=phone,
                file=os.path.basename(pdf),
            )
            move_to_not_sent(pdf)
            continue

        # Send the text message
        if not send_text_message_fast(driver, message_text):
            if not send_text_message(driver, phone, message_text):
                failed += 1
                log_step(
                    "FAIL_TEXT_SEND",
                    phone=phone,
                    file=os.path.basename(pdf),
                )
                move_to_not_sent(pdf)
                continue

        move_to_sent(pdf)
        success += 1
        log_step("DONE_ONE", phone=phone, file=os.path.basename(pdf))
        time.sleep(0.6)

    print(
        f"Batch done. Processed={success + failed} | Sent={success}"
        f" | Failed={failed}. See logs/wa_auto_send_brave.log"
    )
    logging.info(
        f"Batch done. Processed={success + failed} | Sent={success} | Failed={failed}"
    )

    try:
        driver.quit()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[ERROR] {e}")
        logging.error("Unhandled exception in main", exc_info=True)
    print("\n")
    input("Press Enter to close this window...")
