"""POSIX pseudo-terminal bridge for local interactive shells (including ssh)."""
import base64
import fcntl
import json
import os
import pty
import select
import signal
import struct
import sys
import termios

protocol = os.fdopen(3, 'w', buffering=1)
shell = os.environ.get('SHELL', '/bin/sh')
if not os.path.isfile(shell):
    shell = '/bin/sh'
pid, master = pty.fork()
if pid == 0:
    os.environ['TERM'] = 'xterm-256color'
    os.execv(shell, [shell, '-i'])

def stop(*_):
    raise SystemExit

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGHUP, stop)
buffer = b''
try:
    while True:
        readable, _, _ = select.select([master, 0], [], [])
        if master in readable:
            try:
                data = os.read(master, 16384)
            except OSError:
                break
            if not data:
                break
            protocol.write(json.dumps({'type': 'output', 'data': base64.b64encode(data).decode()}) + '\n')
        if 0 in readable:
            chunk = os.read(0, 65536)
            if not chunk:
                break
            buffer += chunk
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                message = json.loads(line)
                if message['type'] == 'input':
                    data = message['data'].encode('utf-8')
                    while data:
                        written = os.write(master, data)
                        data = data[written:]
                elif message['type'] == 'resize':
                    rows = max(2, min(500, int(message['rows'])))
                    cols = max(2, min(500, int(message['cols'])))
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
                elif message['type'] == 'close':
                    raise SystemExit
finally:
    # Close the PTY and signal both the foreground job (e.g. ssh) and the shell.
    try:
        group = os.tcgetpgrp(master)
        if group > 0 and group != os.getpgrp():
            os.killpg(group, signal.SIGHUP)
    except (OSError, ProcessLookupError):
        pass
    os.close(master)
    try:
        os.killpg(pid, signal.SIGHUP)
    except (OSError, ProcessLookupError):
        pass
