"""Document parsing in a killable process with bounded output and resources."""
import sys
import zipfile
from pathlib import Path

MAX_TEXT = 60_000
MAX_PAGES = 200
MAX_EXPANDED = 32 * 1024 * 1024


def extract(path: Path) -> str:
    if path.suffix.lower() == '.pdf':
        import fitz
        parts = []
        remaining = MAX_TEXT
        with fitz.open(path) as document:
            if document.page_count > MAX_PAGES:
                raise ValueError('Documento excede 200 páginas.')
            for page in document:
                part = page.get_text('text')[:remaining]
                parts.append(part)
                remaining -= len(part) + 1
                if remaining <= 0:
                    break
        return '\n'.join(parts)[:MAX_TEXT]
    if path.suffix.lower() == '.docx':
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 2000 or sum(item.file_size for item in infos) > MAX_EXPANDED:
                raise ValueError('DOCX excede o limite descompactado.')
            if 'word/document.xml' not in archive.namelist():
                raise ValueError('DOCX inválido.')
        from docx import Document
        parts = []
        remaining = MAX_TEXT
        for paragraph in Document(path).paragraphs:
            part = paragraph.text[:remaining]
            parts.append(part)
            remaining -= len(part) + 1
            if remaining <= 0:
                break
        return '\n'.join(parts)[:MAX_TEXT]
    with path.open(encoding='utf-8', errors='replace') as source:
        return source.read(MAX_TEXT)


if __name__ == '__main__':
    if sys.platform != 'win32':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    try:
        sys.stdout.buffer.write(extract(Path(sys.argv[1])).encode('utf-8'))
    except Exception:
        sys.stderr.write('Não foi possível processar o documento dentro dos limites permitidos.')
        sys.exit(1)
