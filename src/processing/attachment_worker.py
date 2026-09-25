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


def apply_resource_limits(max_memory_bytes: int = 512 * 1024 * 1024, max_cpu_seconds: int = 15) -> bool:
    """Apply strict process memory and CPU limits on both Unix and Windows."""
    if sys.platform != 'win32':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (max_memory_bytes, max_memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (max_cpu_seconds, max_cpu_seconds))
        return True
    try:
        import ctypes
        import os
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ('ReadOperationCount', ctypes.c_uint64),
                ('WriteOperationCount', ctypes.c_uint64),
                ('OtherOperationCount', ctypes.c_uint64),
                ('ReadTransferCount', ctypes.c_uint64),
                ('WriteTransferCount', ctypes.c_uint64),
                ('OtherTransferCount', ctypes.c_uint64),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ('PerProcessUserTimeLimit', ctypes.c_int64),
                ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', ctypes.c_uint32),
                ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', ctypes.c_uint32),
                ('Affinity', ctypes.c_size_t),
                ('PriorityClass', ctypes.c_uint32),
                ('SchedulingClass', ctypes.c_uint32),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ('IoInfo', IO_COUNTERS),
                ('ProcessMemoryLimit', ctypes.c_size_t),
                ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t),
                ('PeakJobMemoryUsed', ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x0100
        JOB_OBJECT_LIMIT_JOB_MEMORY = 0x0200
        JOB_OBJECT_LIMIT_PROCESS_TIME = 0x0002
        JobObjectExtendedLimitInformation = 9

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        hJob = kernel32.CreateJobObjectW(None, None)
        if not hJob:
            return False

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
            JOB_OBJECT_LIMIT_PROCESS_MEMORY |
            JOB_OBJECT_LIMIT_JOB_MEMORY |
            JOB_OBJECT_LIMIT_PROCESS_TIME
        )
        info.BasicLimitInformation.PerProcessUserTimeLimit = int(max_cpu_seconds * 10_000_000)
        info.ProcessMemoryLimit = max_memory_bytes
        info.JobMemoryLimit = max_memory_bytes

        set_ok = kernel32.SetInformationJobObject(
            hJob,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not set_ok:
            kernel32.CloseHandle(hJob)
            return False

        hProc = kernel32.OpenProcess(0x1F0FFF, False, os.getpid())
        if not hProc:
            kernel32.CloseHandle(hJob)
            return False

        assign_ok = kernel32.AssignProcessToJobObject(hJob, hProc)
        kernel32.CloseHandle(hProc)

        global _job_handle_holder
        _job_handle_holder = hJob
        return bool(assign_ok)
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    if not apply_resource_limits():
        sys.stderr.write('Falha ao aplicar limites de isolamento de processo.')
        return 1
    if len(argv) < 2:
        sys.stderr.write('Uso: python -m src.processing.attachment_worker <caminho_arquivo>')
        return 1
    try:
        sys.stdout.buffer.write(extract(Path(argv[1])).encode('utf-8'))
        return 0
    except Exception:
        sys.stderr.write('Não foi possível processar o documento dentro dos limites permitidos.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
