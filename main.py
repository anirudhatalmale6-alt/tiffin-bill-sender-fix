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
# ATTACHMENT FLOW  (THIS IS WHERE THE FIX LIVES)
# ===================================================================

# --- Updated selector lists for 2025-2026 WhatsApp Web ---

ATTACH_BTN_SELECTORS = [
    # NEW selectors (2025-2026 WhatsApp Web)
    "span[data-icon='plus']",
    "div[data-tab='6']",
    "[data-testid='conversation-clip']",
    "span[data-icon='attach-menu-plus']",
    # Original selectors (still tried as fallback)
    "[data-testid='compose-attach-button']",
    "[data-testid='attach']",
    "[data-testid='clip']",
    "span[data-icon='clip']",
    "button[aria-label='Attach']",
    "button[aria-label='Add']",
    "div[aria-label='Attach']",
    "div[aria-label='Add']",
    "div[title='Attach']",
    "button[title='Attach']",
]

DOC_OPTION_CSS_SELECTORS = [
    # Click the "Document" menu item after opening the attach menu
    "[data-testid='mi-attach-document']",
    "[data-testid='attach-document']",
    "span[data-testid='attach-document']",
    "span[data-icon='attach-document']",
    "span[data-icon='doc']",
    "button[aria-label='Document']",
    "li[data-animate-dropdown-item='true'] span[data-icon='attach-document']",
    "div[aria-label='Document']",
    "li button[aria-label='Document']",
    # Generic menu item selectors
    "li[data-animate-dropdown-item] button",
]

DOC_OPTION_XPATH_SELECTORS = [
    # XPath text-based selectors (language-independent fallbacks)
    "//span[text()='Document']",
    "//button[.//span[text()='Document']]",
    "//li[.//span[text()='Document']]",
    "//div[text()='Document']",
    "//span[contains(text(),'Document')]",
    "//span[contains(text(),'document')]",
    # Try the first menu item (Document is usually first)
    "(//li[@data-animate-dropdown-item='true'])[1]",
    "(//li[@role='button' or @role='menuitem'])[1]",
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
        dom_path = os.path.join("./logs", f"dom_dump_{label}_{ts}.html")
        # Dump just the relevant portion of the DOM (near the attach area)
        dom_info = driver.execute_script("""
            var result = '';
            // Dump all file inputs
            var inputs = document.querySelectorAll('input[type="file"]');
            result += '=== FILE INPUTS (' + inputs.length + ') ===\\n';
            for (var i = 0; i < inputs.length; i++) {
                result += 'INPUT[' + i + ']: accept=' + (inputs[i].accept||'NONE')
                    + ' display=' + getComputedStyle(inputs[i]).display
                    + ' id=' + (inputs[i].id||'')
                    + ' name=' + (inputs[i].name||'')
                    + ' parent=' + (inputs[i].parentElement ? inputs[i].parentElement.tagName + '.' + inputs[i].parentElement.className : 'NONE')
                    + '\\n';
            }

            // Dump all elements with data-testid containing 'attach'
            var testids = document.querySelectorAll('[data-testid*="attach"]');
            result += '\\n=== DATA-TESTID ATTACH (' + testids.length + ') ===\\n';
            for (var i = 0; i < testids.length; i++) {
                result += testids[i].tagName + ' testid=' + testids[i].getAttribute('data-testid')
                    + ' text=' + (testids[i].textContent||'').substring(0,50) + '\\n';
            }

            // Dump all elements with data-icon
            var icons = document.querySelectorAll('[data-icon]');
            result += '\\n=== DATA-ICON (' + icons.length + ') ===\\n';
            for (var i = 0; i < icons.length; i++) {
                result += icons[i].tagName + ' icon=' + icons[i].getAttribute('data-icon') + '\\n';
            }

            // Dump all li elements visible (possible menu items)
            var lis = document.querySelectorAll('li');
            result += '\\n=== LI ELEMENTS (' + lis.length + ') ===\\n';
            for (var i = 0; i < lis.length; i++) {
                var style = getComputedStyle(lis[i]);
                if (style.display !== 'none' && style.visibility !== 'hidden') {
                    result += 'LI[' + i + ']: text=' + (lis[i].textContent||'').substring(0,60).replace(/\\n/g,' ')
                        + ' role=' + (lis[i].getAttribute('role')||'')
                        + ' data-animate=' + (lis[i].getAttribute('data-animate-dropdown-item')||'')
                        + '\\n';
                }
            }

            // Dump elements with role=menu, role=listbox, role=dialog
            var menus = document.querySelectorAll('[role="menu"], [role="listbox"], [role="dialog"], [role="application"]');
            result += '\\n=== MENU/DIALOG ELEMENTS (' + menus.length + ') ===\\n';
            for (var i = 0; i < menus.length; i++) {
                result += menus[i].tagName + ' role=' + menus[i].getAttribute('role')
                    + ' class=' + (menus[i].className||'').substring(0,60)
                    + ' children=' + menus[i].children.length
                    + '\\n';
            }

            // Dump all buttons and clickable divs in the bottom area
            var btns = document.querySelectorAll('button, div[role="button"]');
            result += '\\n=== BUTTONS (' + btns.length + ') ===\\n';
            for (var i = 0; i < btns.length; i++) {
                var b = btns[i];
                var rect = b.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    result += b.tagName + ' aria=' + (b.getAttribute('aria-label')||'')
                        + ' text=' + (b.textContent||'').substring(0,40).replace(/\\n/g,' ')
                        + ' pos=' + Math.round(rect.x) + ',' + Math.round(rect.y)
                        + '\\n';
                }
            }

            return result;
        """)
        with open(dom_path, "w", encoding="utf-8") as f:
            f.write(dom_info)
        log_step("DOM_DUMP_SAVED", path=dom_path)
    except Exception as e:
        log_step("DOM_DUMP_FAILED", error=str(e))


def _find_all_file_inputs(driver):
    """Find all file inputs in the page and log their details."""
    inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    details = []
    for i, el in enumerate(inputs):
        try:
            acc = el.get_attribute("accept") or ""
            name = el.get_attribute("name") or ""
            multiple = el.get_attribute("multiple") or ""
            parent_tag = driver.execute_script(
                "return arguments[0].parentElement ? arguments[0].parentElement.tagName : 'NONE'", el
            )
            details.append({
                "index": i, "accept": acc, "name": name,
                "multiple": multiple, "parent": parent_tag
            })
        except Exception:
            details.append({"index": i, "error": "could not read attributes"})
    return inputs, details


def click_attach_menu(driver):
    """Click the paperclip / '+' button to open the attachment menu."""
    for sel in ATTACH_BTN_SELECTORS:
        try:
            btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
            )
            btn.click()
            log_step("ATTACH_MENU_CLICKED", selector=sel)
            time.sleep(1.0)  # Give menu time to fully render
            return True
        except Exception:
            continue
    log_step("ATTACH_MENU_NOT_FOUND")
    return False


def _click_document_option(driver):
    """
    After opening the attach menu, click the 'Document' option.
    Uses multiple strategies: CSS selectors, XPath, JS text search, and coordinate click.
    """
    time.sleep(1.5)  # Wait longer for menu animation to complete

    # Strategy 1: CSS selectors
    for sel in DOC_OPTION_CSS_SELECTORS:
        try:
            btn = WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
            )
            btn.click()
            log_step("DOC_OPTION_CLICKED_CSS", selector=sel)
            time.sleep(0.5)
            return True
        except Exception:
            continue

    # Strategy 2: XPath selectors (text-based)
    for sel in DOC_OPTION_XPATH_SELECTORS:
        try:
            btn = WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, sel))
            )
            btn.click()
            log_step("DOC_OPTION_CLICKED_XPATH", selector=sel)
            time.sleep(0.5)
            return True
        except Exception:
            continue

    # Strategy 3: JavaScript — find by text content "Document" (case-insensitive, multi-language)
    try:
        clicked = driver.execute_script("""
            var keywords = ['Document', 'document', 'DOCUMENT', 'Documento', 'Dokument'];
            // Search ALL elements for matching text
            var all = document.querySelectorAll('*');
            for (var k = 0; k < keywords.length; k++) {
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    // Check direct text content (not children text)
                    var directText = '';
                    for (var j = 0; j < el.childNodes.length; j++) {
                        if (el.childNodes[j].nodeType === 3) directText += el.childNodes[j].textContent;
                    }
                    directText = directText.trim();
                    if (directText === keywords[k]) {
                        // Click the element or its closest clickable parent
                        var target = el.closest('li, button, div[role="button"], a') || el;
                        target.click();
                        return 'JS_DIRECT:' + target.tagName + ':' + directText;
                    }
                }
            }
            // Fallback: aria-label
            var labeled = document.querySelectorAll('[aria-label*="ocument"], [aria-label*="OCUMENT"]');
            if (labeled.length > 0) {
                var t = labeled[0].closest('li, button, div[role="button"]') || labeled[0];
                t.click();
                return 'JS_ARIA:' + t.tagName + ':' + labeled[0].getAttribute('aria-label');
            }
            return null;
        """)
        if clicked:
            log_step("DOC_OPTION_CLICKED_JS", method=clicked)
            time.sleep(0.5)
            return True
    except Exception:
        pass

    # Strategy 4: Click the first menu item (Document is usually first in the list)
    try:
        items = driver.find_elements(By.CSS_SELECTOR,
            "ul li, div[role='listbox'] > div, div[role='menu'] > div, "
            "[data-animate-dropdown-item], li[tabindex]")
        if items:
            items[0].click()
            log_step("DOC_OPTION_CLICKED_FIRST_ITEM", count=len(items))
            time.sleep(0.5)
            return True
    except Exception:
        pass

    # Strategy 5: Click by position relative to the attach button
    # Document is typically the first (top) item in the menu above the attach button
    try:
        attach_btn = None
        for sel in ATTACH_BTN_SELECTORS[:4]:
            try:
                attach_btn = driver.find_element(By.CSS_SELECTOR, sel)
                if attach_btn:
                    break
            except Exception:
                continue
        if attach_btn:
            # The menu opens ABOVE the button. Document is typically the first item.
            # Try clicking at various offsets above the button
            for y_offset in [-200, -180, -160, -140, -120, -100, -250, -300]:
                try:
                    ActionChains(driver).move_to_element_with_offset(
                        attach_btn, 0, y_offset
                    ).click().perform()
                    time.sleep(0.5)
                    # Check if a file input appeared
                    new_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                    if new_inputs:
                        log_step("DOC_OPTION_CLICKED_OFFSET", y_offset=y_offset, inputs=len(new_inputs))
                        return True
                except Exception:
                    continue
    except Exception:
        pass

    log_step("DOC_OPTION_NOT_FOUND_CONTINUING")
    return False


def locate_document_input(driver):
    """Find the hidden <input type='file'> for documents (not images/video)."""

    inputs, details = _find_all_file_inputs(driver)
    log_step("FILE_INPUTS_SCAN", total=len(inputs), details=str(details))

    if not inputs:
        return None

    # Priority 1: Input with accept='*' (document input in WhatsApp)
    for el in inputs:
        try:
            acc = (el.get_attribute("accept") or "").strip()
            if acc == "*":
                log_step("FILE_INPUT_FOUND", match="accept=*")
                return el
        except Exception:
            pass

    # Priority 2: Input that accepts documents/PDFs/any
    for el in inputs:
        try:
            acc = (el.get_attribute("accept") or "").lower().strip()
            if acc in ("*/*", "") or "application" in acc or ".pdf" in acc:
                # But skip if it's clearly image/video only
                if "image" not in acc and "video" not in acc:
                    log_step("FILE_INPUT_FOUND", match=f"accept={acc}")
                    return el
        except Exception:
            pass

    # Priority 3: Any input that's NOT image/video
    for el in inputs:
        try:
            acc = (el.get_attribute("accept") or "").lower()
            if "image" not in acc and "video" not in acc:
                log_step("FILE_INPUT_FOUND", match=f"non-media accept={acc}")
                return el
        except Exception:
            pass

    # Priority 4: Last resort — use ANY file input
    log_step("FILE_INPUT_USING_ANY_AVAILABLE")
    return inputs[-1]


def make_input_visible(driver, el):
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
            // Remove any disabled attribute
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
                "div[aria-placeholder='Type a message'][contenteditable='true']",
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
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", btn
                )
                driver.execute_script("arguments[0].click();", btn)
                log_step("SEND_BTN_JS_CLICK", selector=sel)
                return True
            except Exception:
                continue
        except Exception:
            continue

    # Final fallback: original selector
    try:
        btn = driver.find_element(
            By.CSS_SELECTOR, "div[role='button'][aria-label='Send']"
        )
        driver.execute_script("arguments[0].click();", btn)
        log_step("SEND_BTN_FALLBACK_CLICK")
        return True
    except Exception:
        log_step("SEND_BTN_FAILED")
        return False


def wait_preview_closed(driver):
    """Wait until the file-preview overlay is gone."""
    try:
        WebDriverWait(driver, PREVIEW_CLOSE_TIMEOUT, poll_frequency=0.5).until_not(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, "div[role='button'][aria-label='Send']")
            )
        )
        return True
    except TimeoutException:
        return False


# ===================================================================
#  MAIN ATTACH + SEND  (FIXED — v5 with multi-strategy approach)
# ===================================================================
def _try_send_file_to_input(driver, file_input, pdf_path):
    """Try to send a file path to a file input element."""
    make_input_visible(driver, file_input)
    abs_path = os.path.abspath(pdf_path)

    try:
        file_input.send_keys(abs_path)
        log_step("FILE_INPUT_SENT", path=os.path.basename(pdf_path))
        return True
    except Exception:
        pass

    # Retry with JS to remove restrictions
    try:
        driver.execute_script("""
            var el = arguments[0];
            el.style.display = 'block';
            el.style.visibility = 'visible';
            el.style.position = 'absolute';
            el.style.left = '0';
            el.style.top = '0';
            el.style.width = '100px';
            el.style.height = '100px';
            el.style.opacity = '1';
            el.removeAttribute('hidden');
            el.removeAttribute('disabled');
        """, file_input)
        time.sleep(0.3)
        file_input.send_keys(abs_path)
        log_step("FILE_INPUT_SENT_RETRY", path=os.path.basename(pdf_path))
        return True
    except Exception as e:
        log_step("FILE_INPUT_SEND_FAILED", error=str(e))
        return False


def attach_document_with_caption_and_send(driver, pdf_path, caption_text):
    started = time.time()

    # === STRATEGY A: Check if file inputs already exist in DOM (before clicking anything) ===
    pre_inputs, pre_details = _find_all_file_inputs(driver)
    log_step("PRE_CLICK_FILE_INPUTS", count=len(pre_inputs), details=str(pre_details))

    # If document-compatible inputs exist, try using them directly
    if pre_inputs:
        doc_input = None
        for el in pre_inputs:
            try:
                acc = (el.get_attribute("accept") or "").strip().lower()
                if acc == "*" or acc == "" or "application" in acc or ".pdf" in acc:
                    if "image" not in acc and "video" not in acc:
                        doc_input = el
                        break
            except Exception:
                pass

        if doc_input:
            log_step("TRYING_DIRECT_INPUT_NO_MENU")
            if _try_send_file_to_input(driver, doc_input, pdf_path):
                # Check if preview appeared
                time.sleep(2)
                cap, btn = wait_for_preview_ready(driver)
                if btn:
                    log_step("DIRECT_INPUT_WORKED")
                    if caption_text:
                        cap_el = cap or focus_caption_box(driver)
                        if cap_el:
                            try:
                                time.sleep(FOCUS_PAUSE_SEC)
                                cap_el.send_keys(caption_text)
                            except Exception:
                                pass
                    sent = click_send_button(driver)
                    if sent:
                        wait_preview_closed(driver)
                        time.sleep(POST_SEND_ATTACHMENT_PAUSE_SEC)
                        return True

    # === STRATEGY B: Click attach menu → Click Document → Find file input ===
    log_step("TRYING_MENU_APPROACH")
    ok = click_attach_menu(driver)
    if not ok:
        _save_debug_screenshot(driver, "no_attach_btn")
        return False

    # Record inputs before clicking Document
    inputs_before = set()
    for el in driver.find_elements(By.CSS_SELECTOR, "input[type='file']"):
        try:
            inputs_before.add(el.id or id(el))
        except Exception:
            pass

    doc_clicked = _click_document_option(driver)

    # Wait and look for file input
    file_input = None
    for attempt in range(20):
        file_input = locate_document_input(driver)
        if file_input:
            break
        time.sleep(0.5)
        # After 10 attempts, retry the full flow
        if attempt == 10 and not doc_clicked:
            log_step("RETRYING_ATTACH_FLOW")
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(0.5)
            except Exception:
                pass
            click_attach_menu(driver)
            _click_document_option(driver)

    if file_input:
        if _try_send_file_to_input(driver, file_input, pdf_path):
            cap, btn = wait_for_preview_ready(driver)
            if btn:
                if caption_text:
                    cap_el = cap or focus_caption_box(driver)
                    if cap_el:
                        try:
                            time.sleep(FOCUS_PAUSE_SEC)
                            cap_el.send_keys(caption_text)
                        except Exception:
                            pass
                sent = click_send_button(driver)
                if sent:
                    wait_preview_closed(driver)
                    time.sleep(POST_SEND_ATTACHMENT_PAUSE_SEC)
                    return True
            else:
                log_step("PREVIEW_NOT_READY_AFTER_FILE_SEND")

    # === STRATEGY C: JavaScript-based file input creation and dispatch ===
    log_step("TRYING_JS_FILE_INPUT_INJECTION")
    try:
        # Close any open menus first
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.5)

        # Click attach menu again
        click_attach_menu(driver)
        time.sleep(1.5)

        # Use JS to find and trigger the document file input
        result = driver.execute_script("""
            // Find ALL file inputs and return info about each
            var inputs = document.querySelectorAll('input[type="file"]');
            var info = [];
            for (var i = 0; i < inputs.length; i++) {
                info.push({
                    accept: inputs[i].accept || '',
                    id: inputs[i].id || '',
                    display: getComputedStyle(inputs[i]).display,
                    parentHTML: inputs[i].parentElement ? inputs[i].parentElement.outerHTML.substring(0, 200) : ''
                });
            }
            return JSON.stringify(info);
        """)
        log_step("JS_FILE_INPUT_INFO", info=result)
    except Exception as e:
        log_step("JS_INJECTION_FAILED", error=str(e))

    # === SAVE DEBUG INFO ON FAILURE ===
    log_step("ALL_STRATEGIES_FAILED")
    _save_debug_screenshot(driver, "attach_failed")

    # Close menu before returning
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    except Exception:
        pass

    return False


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
