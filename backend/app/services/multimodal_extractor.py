"""
Extractor multimodal con soporte nativo para PDFs de texto, tablas, PDFs escaneados/visuales
(mediante OCR local o análisis visual estructural), Markdown, TXT, CSV, JSON, DOCX y XLSX.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PageExtraction:
    page_number: int
    extraction_method: str
    char_count: int
    text: str
    warnings: List[str] = field(default_factory=list)


@dataclass
class ExtractedDocument:
    file_path: str
    filename: str
    suffix: str
    text: str
    char_count: int
    extraction_method: str
    pages: List[PageExtraction] = field(default_factory=list)
    tables_markdown: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_audit_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "suffix": self.suffix,
            "extraction_method": self.extraction_method,
            "char_count": self.char_count,
            "page_count": len(self.pages),
            "tables_count": len(self.tables_markdown),
            "warnings": list(self.warnings),
            "pages": [
                {
                    "page_number": p.page_number,
                    "extraction_method": p.extraction_method,
                    "char_count": p.char_count,
                    "warnings": list(p.warnings),
                }
                for p in self.pages
            ],
        }


def read_text_with_fallback(file_path: str) -> str:
    """Lee texto detectando codificación con múltiples respaldos."""
    data = Path(file_path).read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass

    encoding = None
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best and best.encoding:
            encoding = best.encoding
    except Exception:
        pass

    if not encoding:
        try:
            import chardet

            result = chardet.detect(data)
            encoding = result.get("encoding") if result else None
        except Exception:
            pass

    return data.decode(encoding or "utf-8", errors="replace")


def _ocr_image_rapidocr(image_path: str) -> str:
    try:
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR()
        result, _ = engine(image_path)
        if not result:
            return ""
        return "\n".join(str(line[1]).strip() for line in result if len(line) >= 2 and str(line[1]).strip())
    except Exception:
        return ""


def _ocr_image_pytesseract(image_path: str) -> str:
    try:
        import pytesseract
        from PIL import Image

        with Image.open(image_path) as img:
            try:
                return pytesseract.image_to_string(img, lang="spa+eng").strip()
            except Exception:
                return pytesseract.image_to_string(img).strip()
    except Exception:
        return ""


def _ocr_image_winrt(image_path: str) -> str:
    """Invoca Windows.Media.Ocr nativo de Windows sin dependencias externas."""
    if sys.platform != "win32":
        return ""
    ps_script = """
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
function AwaitWinRT($op, $type) {
  $m = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.IsGenericMethod } |
    Select-Object -First 1
  $task = $m.MakeGenericMethod($type).Invoke($null, @($op))
  $task.Wait()
  return $task.Result
}
$imgPath = $env:MF_OCR_IMAGE_PATH
$file = AwaitWinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($imgPath)) ([Windows.Storage.StorageFile])
$stream = AwaitWinRT ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = AwaitWinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bmp = AwaitWinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
  $lang = [Windows.Globalization.Language]::new('en-US')
  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
}
$res = AwaitWinRT ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Output $res.Text
""".strip()
    encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
    env = os.environ.copy()
    env["MF_OCR_IMAGE_PATH"] = os.path.abspath(image_path)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            env=env,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip()
    except Exception as exc:
        logger.debug("WinRT OCR falló para %s: %s", image_path, exc)
    return ""


def _describe_visual_asset(page: Any, image_path: str, page_num: int, filename: str) -> str:
    """Extrae metadatos visuales y paleta cromática dominante si el OCR no obtiene texto."""
    parts = [
        f"[Contenido visual detectado en '{filename}', página {page_num}]",
        f"Dimensiones de página: {int(page.rect.width)}x{int(page.rect.height)} pt.",
    ]
    try:
        images = page.get_images(full=True)
        if images:
            img_info = ", ".join(f"{im[2]}x{im[3]}px ({im[5]})" for im in images[:5])
            parts.append(f"Láminas/imágenes embebidas ({len(images)}): {img_info}.")
    except Exception:
        pass

    try:
        from PIL import Image

        with Image.open(image_path) as im:
            rgb = im.convert("RGB").resize((64, 64))
            quantized = rgb.quantize(colors=5).convert("RGB")
            colors = sorted(quantized.getcolors(maxcolors=64 * 64) or [], reverse=True)[:5]
            hexes = ", ".join(f"#{r:02X}{g:02X}{b:02X}" for _, (r, g, b) in colors)
            if hexes:
                parts.append(f"Paleta visual dominante detectada en el documento: {hexes}.")
    except Exception:
        pass

    parts.append(
        "Nota de extracción: esta página corresponde a una pieza gráfica/imagen sin capa de texto seleccionable; "
        "la estructura visual fue indexada para mantener trazabilidad documental completa."
    )
    return "\n".join(parts)


def _format_table_markdown(rows: List[List[Any]]) -> str:
    cleaned_rows: List[List[str]] = []
    for row in rows:
        if not row:
            continue
        cleaned_rows.append([str(cell or "").replace("\n", " ").strip() for cell in row])
    if not cleaned_rows:
        return ""
    width = max(len(r) for r in cleaned_rows)
    padded = [r + [""] * (width - len(r)) for r in cleaned_rows]
    header = "| " + " | ".join(padded[0]) + " |"
    sep = "| " + " | ".join("---" for _ in range(width)) + " |"
    body = ["| " + " | ".join(r) + " |" for r in padded[1:]]
    return "\n".join([header, sep] + body)


class MultimodalExtractor:
    """Extractor unificado con respaldo OCR local y diagnóstico por página."""

    SUPPORTED_EXTENSIONS = {
        ".pdf",
        ".md",
        ".markdown",
        ".txt",
        ".csv",
        ".json",
        ".xlsx",
        ".docx",
    }

    MIN_NATIVE_PAGE_CHARS = 40

    @classmethod
    def is_supported(cls, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in cls.SUPPORTED_EXTENSIONS

    @classmethod
    def extract(cls, file_path: str) -> ExtractedDocument:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {file_path}")

        suffix = path.suffix.lower()
        if suffix not in cls.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Formato de archivo no soportado: {suffix}")

        if suffix == ".pdf":
            return cls._extract_pdf(path)
        if suffix in {".md", ".markdown", ".txt"}:
            text = read_text_with_fallback(str(path))
            method = "markdown_text" if suffix in {".md", ".markdown"} else "plain_text"
            return ExtractedDocument(
                file_path=str(path),
                filename=path.name,
                suffix=suffix,
                text=text,
                char_count=len(text),
                extraction_method=method,
            )
        if suffix == ".csv":
            return cls._extract_csv(path)
        if suffix == ".json":
            return cls._extract_json(path)
        if suffix == ".docx":
            return cls._extract_docx(path)
        if suffix == ".xlsx":
            return cls._extract_xlsx(path)
        raise ValueError(f"No se pudo procesar el formato: {suffix}")

    @classmethod
    def _extract_pdf(cls, path: Path) -> ExtractedDocument:
        import fitz  # PyMuPDF

        pages_out: List[PageExtraction] = []
        tables_all: List[str] = []
        warnings_all: List[str] = []
        methods_used = set()

        with fitz.open(str(path)) as doc:
            for idx, page in enumerate(doc, start=1):
                native_text = (page.get_text("text") or "").strip()
                page_tables: List[str] = []
                if hasattr(page, "find_tables"):
                    try:
                        tf = page.find_tables()
                        for tbl in getattr(tf, "tables", []) or []:
                            md_tbl = _format_table_markdown(tbl.extract())
                            if md_tbl:
                                page_tables.append(md_tbl)
                    except Exception:
                        pass
                tables_all.extend(page_tables)

                if len(native_text) >= cls.MIN_NATIVE_PAGE_CHARS:
                    combined = native_text
                    if page_tables:
                        combined += "\n\n" + "\n\n".join(page_tables)
                    methods_used.add("pymupdf_text")
                    pages_out.append(
                        PageExtraction(
                            page_number=idx,
                            extraction_method="pymupdf_text",
                            char_count=len(combined),
                            text=combined,
                        )
                    )
                    continue

                # Página visual/escaneada: renderizar a PNG y correr cascada OCR
                page_warnings = [f"Página {idx} sin texto nativo suficiente ({len(native_text)} chars); aplicando OCR."]
                ocr_text = ""
                method = "visual_metadata_fallback"
                tmp_png = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as fh:
                        tmp_png = fh.name
                    page.get_pixmap(dpi=200).save(tmp_png)

                    for name, fn in (
                        ("ocr_rapidocr", _ocr_image_rapidocr),
                        ("ocr_pytesseract", _ocr_image_pytesseract),
                        ("ocr_winrt", _ocr_image_winrt),
                    ):
                        candidate = fn(tmp_png)
                        if len(candidate.strip()) >= 15:
                            ocr_text = candidate.strip()
                            method = name
                            break

                    visual_summary = _describe_visual_asset(page, tmp_png, idx, path.name)
                    if ocr_text:
                        combined = f"{ocr_text}\n\n{visual_summary}"
                    else:
                        page_warnings.append("Ningún motor OCR extrajo texto legible; usando ficha visual estructural.")
                        combined = visual_summary
                finally:
                    if tmp_png and os.path.exists(tmp_png):
                        try:
                            os.remove(tmp_png)
                        except OSError:
                            pass

                methods_used.add(method)
                warnings_all.extend(page_warnings)
                pages_out.append(
                    PageExtraction(
                        page_number=idx,
                        extraction_method=method,
                        char_count=len(combined),
                        text=combined,
                        warnings=page_warnings,
                    )
                )

        full_text = "\n\n".join(p.text for p in pages_out if p.text.strip())
        overall_method = "+".join(sorted(methods_used)) if methods_used else "pymupdf_empty"
        return ExtractedDocument(
            file_path=str(path),
            filename=path.name,
            suffix=".pdf",
            text=full_text,
            char_count=len(full_text),
            extraction_method=overall_method,
            pages=pages_out,
            tables_markdown=tables_all,
            warnings=warnings_all,
        )

    @classmethod
    def _extract_csv(cls, path: Path) -> ExtractedDocument:
        raw = read_text_with_fallback(str(path))
        reader = csv.reader(io.StringIO(raw))
        rows = list(reader)
        md_table = _format_table_markdown(rows[:200]) if rows else raw
        return ExtractedDocument(
            file_path=str(path),
            filename=path.name,
            suffix=".csv",
            text=md_table or raw,
            char_count=len(md_table or raw),
            extraction_method="csv_markdown_table",
            tables_markdown=[md_table] if md_table else [],
        )

    @classmethod
    def _extract_json(cls, path: Path) -> ExtractedDocument:
        raw = read_text_with_fallback(str(path))
        try:
            pretty = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        except Exception:
            pretty = raw
        return ExtractedDocument(
            file_path=str(path),
            filename=path.name,
            suffix=".json",
            text=pretty,
            char_count=len(pretty),
            extraction_method="json_pretty",
        )

    @classmethod
    def _extract_docx(cls, path: Path) -> ExtractedDocument:
        try:
            import docx  # type: ignore

            document = docx.Document(str(path))
            parts = [p.text.strip() for p in document.paragraphs if p.text.strip()]
            for tbl in document.tables:
                md = _format_table_markdown([[c.text for c in row.cells] for row in tbl.rows])
                if md:
                    parts.append(md)
            text = "\n\n".join(parts)
            return ExtractedDocument(
                file_path=str(path),
                filename=path.name,
                suffix=".docx",
                text=text,
                char_count=len(text),
                extraction_method="python_docx",
            )
        except ImportError:
            # Lector ZIP/XML nativo sin dependencias externas
            parts: List[str] = []
            with zipfile.ZipFile(str(path)) as zf:
                xml_bytes = zf.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
            for p_elem in root.iter():
                if p_elem.tag.endswith("}p"):
                    runs = [t.text for t in p_elem.iter() if t.tag.endswith("}t") and t.text]
                    line = "".join(runs).strip()
                    if line:
                        parts.append(line)
            text = "\n\n".join(parts)
            return ExtractedDocument(
                file_path=str(path),
                filename=path.name,
                suffix=".docx",
                text=text,
                char_count=len(text),
                extraction_method="docx_xml_zip",
            )

    @classmethod
    def _extract_xlsx(cls, path: Path) -> ExtractedDocument:
        tables: List[str] = []
        parts: List[str] = []
        try:
            import openpyxl  # type: ignore

            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows = [[cell for cell in row] for row in ws.iter_rows(values_only=True)][:200]
                md = _format_table_markdown(rows)
                if md:
                    tables.append(md)
                    parts.append(f"### Hoja: {sheet_name}\n{md}")
            text = "\n\n".join(parts)
            return ExtractedDocument(
                file_path=str(path),
                filename=path.name,
                suffix=".xlsx",
                text=text,
                char_count=len(text),
                extraction_method="openpyxl",
                tables_markdown=tables,
            )
        except ImportError:
            # Lector ZIP/XML nativo básico para XLSX
            with zipfile.ZipFile(str(path)) as zf:
                shared: List[str] = []
                if "xl/sharedStrings.xml" in zf.namelist():
                    sroot = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                    for si in sroot:
                        texts = [t.text or "" for t in si.iter() if t.tag.endswith("}t")]
                        shared.append("".join(texts))
                sheet_files = sorted(n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
                for sf in sheet_files:
                    root = ET.fromstring(zf.read(sf))
                    rows: List[List[str]] = []
                    for row_el in root.iter():
                        if not row_el.tag.endswith("}row"):
                            continue
                        row_vals: List[str] = []
                        for c_el in row_el:
                            if not c_el.tag.endswith("}c"):
                                continue
                            ctype = c_el.attrib.get("t")
                            v_el = next((ch for ch in c_el if ch.tag.endswith("}v")), None)
                            val = v_el.text if v_el is not None and v_el.text is not None else ""
                            if ctype == "s" and val.isdigit() and int(val) < len(shared):
                                val = shared[int(val)]
                            row_vals.append(val)
                        if any(row_vals):
                            rows.append(row_vals)
                    md = _format_table_markdown(rows[:200])
                    if md:
                        tables.append(md)
                        parts.append(f"### {Path(sf).stem}\n{md}")
            text = "\n\n".join(parts)
            return ExtractedDocument(
                file_path=str(path),
                filename=path.name,
                suffix=".xlsx",
                text=text,
                char_count=len(text),
                extraction_method="xlsx_xml_zip",
                tables_markdown=tables,
            )
