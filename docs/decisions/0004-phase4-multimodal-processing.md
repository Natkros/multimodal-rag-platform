# ADR 0004: Phase 4 Multimodal Processing

## Scope

The project brief's Phase 4 pipeline is: page detection → text extraction → OCR →
layout analysis → table extraction → image extraction → visual descriptions → unified
representation → indexing. This phase implements OCR, structured table extraction,
and visual descriptions — genuinely working, tested against real installed OCR
binaries, not just written and left unverified. **Layout analysis with bounding
boxes is explicitly out of scope**: it requires a document-layout detection model
(e.g. LayoutLM, a YOLO-style page-object detector), which is a meaningfully larger
undertaking than wiring up Tesseract/pdfplumber, and nothing downstream in this
project currently consumes bounding boxes. `ExtractedTable`/image chunk metadata omit
`bounding_box` rather than populate it with a fabricated or always-null placeholder —
if it's added later (a real Phase 4 extension, or folded into Phase 5), it should
come with an actual detector behind it.

## System dependencies: Tesseract and Poppler

OCR requires two system binaries, not pip packages:
- **Tesseract** (`pytesseract` is just a subprocess wrapper around the `tesseract` CLI)
- **Poppler** (`pdf2image` shells out to `pdftoppm` to rasterize PDF pages for OCR)

Install:
- **Linux/Docker**: `apt-get install tesseract-ocr poppler-utils` (already added to
  `Dockerfile` and `.github/workflows/ci.yml` — OCR is real in CI, not skipped)
- **macOS**: `brew install tesseract poppler`
- **Windows**: `winget install UB-Mannheim.TesseractOCR` and
  `winget install oschwartz10612.Poppler`, then set `OCR_TESSERACT_CMD` /
  `OCR_POPPLER_PATH` in `.env` to the installed paths — Windows doesn't refresh a
  process's `PATH` until a new shell, which is a bad first-run experience, so the app
  never relies on `PATH` alone for these two binaries when explicit paths are given.

Both binaries are genuinely installed and verified in this development environment —
`tests/unit/test_ocr.py` and the OCR-dependent extraction/pipeline tests run for real
against them, not against mocks, skipping gracefully
(`@pytest.mark.skipif(not is_ocr_available(...))`) only on a machine where they're
absent.

## Graceful degradation is load-bearing, not decorative

Every OCR/vision call in this phase can fail (missing binary, corrupted image,
network error, no API key) without failing the document:
- `app/services/extraction/ocr.py` — `ocr_image_bytes`/`ocr_pdf_pages` return
  `""`/`[]` on any failure, never raise.
- `app/services/generation/vision_describer.py` — `describe_image` returns `None` on
  missing config or any API failure, never raises.
- The ingestion pipeline treats "an image produced zero chunks" as a valid terminal
  state (still `INDEXED`, `chunk_count=0`), not a failure — this was already Phase 2's
  behavior for uncaptioned images; Phase 4 just adds two more chances (OCR, then
  vision) to avoid landing there before falling back to it.

## Images: OCR first, vision caption only if OCR finds nothing

Running both unconditionally would double the cost (an LLM call) for images that OCR
already made searchable. `app/services/extraction/loaders.py`'s `_extract_image` runs
OCR during extraction (deterministic, local, no API key); if that clears
`MIN_OCR_TEXT_LENGTH`, the image is no longer `is_visual_only` and the pipeline never
calls the vision LLM for it. Only genuinely text-free images (photos, most diagrams)
reach `describe_image`.

## Tables: structured, with a disclosed duplication tradeoff

`ExtractedTable(page, headers, rows)` is the source of truth, stored verbatim in
`Chunk.extra_metadata`; `render_table_markdown()` produces the text form used for
embedding. DOCX paragraphs and tables are now extracted separately — a table's cells
are no longer flattened into the surrounding paragraph text. PDF is different: pypdf's
per-page plain-text extraction (used for the page's regular text chunks) still
includes a table's cell text inline, because pypdf has no concept of "this text belongs
to a table" to exclude it — pdfplumber runs as a *second*, independent pass purely to
detect and structure tables, appended as extra chunks. This means a PDF table's content
can appear twice in the index: once as ordinary flowing text, once as a structured
table chunk. Excluding a detected table's region from the plain-text pass would require
reliable bounding-box-to-text-span mapping between two different parsing libraries,
which is exactly the kind of fragile text-diffing logic this project avoids per its
engineering rules ("prefer reproducibility over cleverness"). Documented here as a known
limitation rather than solved with something likely to silently drop real content.

## Images are excluded from chunking-strategy staleness tracking

`app/services/ingestion/staleness.py` flags documents whose `indexed_with_chunking_
strategy` no longer matches current config. Images don't go through `chunk_document()`
at all (see `_build_image_chunks` in `app/services/ingestion/pipeline.py`), so that
field is meaningless for them; the pipeline never stamps it for `file_type == "image"`,
which keeps them correctly excluded from that check (both fields being unset is what
`find_and_flag_stale_documents` treats as "not a chunking-pipeline candidate").

## New chunk-level endpoint

`GET /documents/{document_id}/chunks` exposes `content_type` and `extra_metadata` per
chunk — the only way to actually see a table's structured headers/rows or an image's
OCR text/caption without querying the database directly. Small, scoped addition; not a
general chunk-management API.
