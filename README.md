# Sire-prep
Questionnaire for Sure 2.0

## SMS reference pages

In a question's Guidance tab, the SMS references (e.g. `PAM 16.2`, `H&S 5.3.19`) can be tapped
to see every page of that manual section in a pop-up, opened at the referenced subsection.

The page images (`sms/<manual>/<page>.webp`) and `sms/refs.js` are generated from the SMS Finder
(SMSAPP) index and PDFs. After the manuals or the questions change, run:

    python tools/build_sms_refs.py <path-to-SMSAPP>

then bump `VERSION` (and `PAGES` if the manuals changed) in `sw.js`, commit and push.
Needs Python with PyMuPDF and Pillow. Pages are 1100 px WebP at quality 62 (741 pages, about 78 MB).
Run it with `--redo` to render every page again after changing the image settings.
