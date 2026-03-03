TiffinBillSender - FIXED VERSION
================================
Bug Fix: WhatsApp Web updated its interface, changing the
attachment button from a paperclip icon to a "+" (plus) icon.
The old selectors no longer matched, so PDFs could never attach.

WHAT WAS FIXED:
1. Updated the attach menu button selectors (new "plus" icon,
   new data-tab attribute, etc.)
2. Added a step to click the "Document" option in the
   attachment menu (required by newer WhatsApp Web versions).
3. Improved the file input detection to try exact selectors
   first (accept="*") before falling back to filtering.
4. Updated the send button selectors for compatibility.

HOW TO USE (choose one):

  OPTION A - Quick run (requires Python installed):
    1. Copy this entire folder next to your pdfs_folder
    2. Double-click RUN_WITHOUT_EXE.bat

  OPTION B - Build a new .exe:
    1. Make sure Python 3.x is installed on your Windows PC
    2. Double-click BUILD_EXE.bat
    3. The new TiffinBillSender.exe will be in the "dist" folder
    4. Replace your old .exe with the new one

  OPTION C - Replace main.py only (if you have the source):
    1. Copy main.py over your old main.py
    2. Re-run your existing setup
