"""Windows pseudo-console (ConPTY) bridge for local interactive shells (including ssh).

Same JSON-lines protocol as terminal-worker.py: messages arrive on stdin, and output
goes to stdout (Windows has no portable fd 3). Requires Windows 10 1809+. Uses only
ctypes. The shell runs in a kill-on-close job object, so closing the terminal also
ends anything it started (e.g. an ssh session).
"""
import base64
import ctypes
import json
import os
import shutil
import sys
import threading
from ctypes import wintypes as w

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
STARTF_USESTDHANDLES = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
INFINITE = 0xFFFFFFFF


class COORD(ctypes.Structure):
    _fields_ = [('X', w.SHORT), ('Y', w.SHORT)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [('cb', w.DWORD), ('lpReserved', w.LPWSTR), ('lpDesktop', w.LPWSTR), ('lpTitle', w.LPWSTR),
                ('dwX', w.DWORD), ('dwY', w.DWORD), ('dwXSize', w.DWORD), ('dwYSize', w.DWORD),
                ('dwXCountChars', w.DWORD), ('dwYCountChars', w.DWORD), ('dwFillAttribute', w.DWORD),
                ('dwFlags', w.DWORD), ('wShowWindow', w.WORD), ('cbReserved2', w.WORD),
                ('lpReserved2', ctypes.c_void_p), ('hStdInput', w.HANDLE), ('hStdOutput', w.HANDLE),
                ('hStdError', w.HANDLE)]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [('StartupInfo', STARTUPINFOW), ('lpAttributeList', ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', w.HANDLE), ('hThread', w.HANDLE), ('dwProcessId', w.DWORD), ('dwThreadId', w.DWORD)]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', w.DWORD),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION), ('IoInfo', IO_COUNTERS),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


def _sig(name, restype, *argtypes):
    fn = getattr(kernel32, name)
    fn.restype, fn.argtypes = restype, list(argtypes)
    return fn


CreatePipe = _sig('CreatePipe', w.BOOL, ctypes.POINTER(w.HANDLE), ctypes.POINTER(w.HANDLE), ctypes.c_void_p, w.DWORD)
CreatePseudoConsole = _sig('CreatePseudoConsole', ctypes.c_long, COORD, w.HANDLE, w.HANDLE, w.DWORD,
                           ctypes.POINTER(w.HANDLE))
ResizePseudoConsole = _sig('ResizePseudoConsole', ctypes.c_long, w.HANDLE, COORD)
ClosePseudoConsole = _sig('ClosePseudoConsole', None, w.HANDLE)
InitializeProcThreadAttributeList = _sig('InitializeProcThreadAttributeList', w.BOOL, ctypes.c_void_p, w.DWORD,
                                         w.DWORD, ctypes.POINTER(ctypes.c_size_t))
UpdateProcThreadAttribute = _sig('UpdateProcThreadAttribute', w.BOOL, ctypes.c_void_p, w.DWORD, ctypes.c_size_t,
                                 ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p)
DeleteProcThreadAttributeList = _sig('DeleteProcThreadAttributeList', None, ctypes.c_void_p)
CreateProcessW = _sig('CreateProcessW', w.BOOL, w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL,
                      w.DWORD, ctypes.c_void_p, w.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(PROCESS_INFORMATION))
CreateJobObjectW = _sig('CreateJobObjectW', w.HANDLE, ctypes.c_void_p, w.LPCWSTR)
SetInformationJobObject = _sig('SetInformationJobObject', w.BOOL, w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD)
AssignProcessToJobObject = _sig('AssignProcessToJobObject', w.BOOL, w.HANDLE, w.HANDLE)
ResumeThread = _sig('ResumeThread', w.DWORD, w.HANDLE)
WaitForSingleObject = _sig('WaitForSingleObject', w.DWORD, w.HANDLE, w.DWORD)
GetExitCodeProcess = _sig('GetExitCodeProcess', w.BOOL, w.HANDLE, ctypes.POINTER(w.DWORD))
ReadFile = _sig('ReadFile', w.BOOL, w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p)
WriteFile = _sig('WriteFile', w.BOOL, w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p)
CloseHandle = _sig('CloseHandle', w.BOOL, w.HANDLE)


def check(ok, what):
    if not ok:
        raise OSError(ctypes.get_last_error(), f'{what} failed')


def choose_shell() -> str:
    configured = os.environ.get('PRE_TERMINAL_SHELL')
    if configured:
        return configured
    for name in ('pwsh.exe', 'powershell.exe'):
        found = shutil.which(name)
        if found:
            return f'"{found}" -NoLogo'
    return os.environ.get('COMSPEC', 'cmd.exe')


protocol_lock = threading.Lock()


def emit(message: dict) -> None:
    line = (json.dumps(message) + '\n').encode()
    with protocol_lock:
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()


def main() -> None:
    # Pipes: we write keystrokes to in_write; ConPTY writes rendered output to out_read.
    in_read, in_write, out_read, out_write = w.HANDLE(), w.HANDLE(), w.HANDLE(), w.HANDLE()
    check(CreatePipe(ctypes.byref(in_read), ctypes.byref(in_write), None, 0), 'CreatePipe')
    check(CreatePipe(ctypes.byref(out_read), ctypes.byref(out_write), None, 0), 'CreatePipe')
    console = w.HANDLE()
    hr = CreatePseudoConsole(COORD(120, 30), in_read, out_write, 0, ctypes.byref(console))
    if hr != 0:
        raise OSError(hr, 'CreatePseudoConsole failed (Windows 10 1809 or newer is required)')
    CloseHandle(in_read)   # the pseudo console holds its own copies
    CloseHandle(out_write)

    size = ctypes.c_size_t()
    InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attributes = ctypes.create_string_buffer(size.value)
    check(InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)), 'InitializeProcThreadAttributeList')
    check(UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE, console,
                                    ctypes.sizeof(w.HANDLE), None, None), 'UpdateProcThreadAttribute')
    startup = STARTUPINFOEXW()
    startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
    # Our own stdio is the protocol pipe; null std handles make the shell use the pseudo console.
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
    startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
    process = PROCESS_INFORMATION()
    command = ctypes.create_unicode_buffer(choose_shell())
    check(CreateProcessW(None, command, None, None, False,
                         EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED,
                         None, os.getcwd(), ctypes.byref(startup), ctypes.byref(process)), 'CreateProcessW')
    DeleteProcThreadAttributeList(attributes)

    job = CreateJobObjectW(None, None)
    limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    check(SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(limits),
                                  ctypes.sizeof(limits)), 'SetInformationJobObject')
    check(AssignProcessToJobObject(job, process.hProcess), 'AssignProcessToJobObject')
    ResumeThread(process.hThread)
    CloseHandle(process.hThread)

    def pump_output():
        buffer = ctypes.create_string_buffer(16384)
        read = w.DWORD()
        while ReadFile(out_read, buffer, len(buffer), ctypes.byref(read), None) and read.value:
            emit({'type': 'output', 'data': base64.b64encode(buffer.raw[:read.value]).decode()})

    def write_input(data: bytes):
        written = w.DWORD()
        while data:
            if not WriteFile(in_write, data, len(data), ctypes.byref(written), None):
                return
            data = data[written.value:]

    def wait_for_exit():
        WaitForSingleObject(process.hProcess, INFINITE)
        ClosePseudoConsole(console)  # flushes remaining output, then the output pipe hits EOF
        output.join(2)
        code = w.DWORD()
        GetExitCodeProcess(process.hProcess, ctypes.byref(code))
        sys.stdout.flush()
        os._exit(code.value & 0xFF)

    output = threading.Thread(target=pump_output, daemon=True)
    output.start()
    threading.Thread(target=wait_for_exit, daemon=True).start()

    for line in sys.stdin.buffer:
        message = json.loads(line)
        if message['type'] == 'input':
            write_input(message['data'].encode('utf-8'))
        elif message['type'] == 'resize':
            rows = max(2, min(500, int(message['rows'])))
            cols = max(2, min(500, int(message['cols'])))
            ResizePseudoConsole(console, COORD(cols, rows))
        elif message['type'] == 'close':
            break
    # stdin closed or "close": exiting closes the job handle, which kills the shell and its children.
    os._exit(0)


if __name__ == '__main__':
    main()
