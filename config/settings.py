# config/settings.py

# -------- Paths & Folders --------
PDF_DIR = "./pdfs_folder"
SENT_DIR_NAME = "sent_pdfs"

# -------- WhatsApp message template (edit freely) --------
MESSAGE_TEMPLATE = """
Dear Customer,
Your tiffin bill for the month of {MONTH} is attached. Kindly make the payment at the earliest.

Payment Options:
UPI: xxxxxxxxxx@upi
Bank Transfer: [Account Name] - [Account No.] - [IFSC Code]

Thank you for choosing Hommed Tiffin.
"""

# Keep blank to avoid a first "caption" message with the attachment
DOCUMENT_CAPTION = ""

# Country code for phone extraction from filenames
COUNTRY_CODE = "91"

# -------- Browser selection --------
BROWSER = "brave"      # "chrome" or "brave"
CHROME_PATH = ""        # leave empty to auto-detect
BRAVE_PATH = ""         # leave empty to auto-detect
CHROMEDRIVER_PATH = ""  # leave empty to let Selenium Manager fetch automatically

# Headless mode (do NOT use for WA if it’s unreliable for you)
HEADLESS = False

# -------- Timeouts (sec) / Polling --------
CHAT_READY_TIMEOUT = 600
PREVIEW_READY_TIMEOUT = 100
SEND_ATTEMPT_TIMEOUT = 100
PREVIEW_CLOSE_TIMEOUT = 150
PER_DOC_TIMEOUT = 400
PREVIEW_POLL_SECONDS = 0.50

# Very long login/QR wait window (after launch or if WA logs out mid-run)
LONG_LOGIN_WAIT_SEC = 900  # 15 minutes

# -------- Short pauses (sec) --------
PREVIEW_PAUSE_SEC = 3
FOCUS_PAUSE_SEC = 2
POST_SEND_ATTACHMENT_PAUSE_SEC = 10.0

# -------- Batching --------
BATCH_SIZE = 50
