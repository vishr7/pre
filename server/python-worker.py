"""Persistent local notebook kernel. Protocol uses fd 3, separate from user output."""
import ast
import base64
import contextlib
import io
import json
import os
import sys
import time
import traceback

protocol = os.fdopen(3, 'w', buffering=1)
namespace = {'__name__': '__main__'}
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'src'))
os.environ.setdefault('MPLBACKEND', 'Agg')

class Output(io.TextIOBase):
    def __init__(self):
        self.parts = []
        self.size = 0
    def write(self, text):
        remaining = max(0, 100000 - self.size)
        self.parts.append(text[:remaining])
        self.size += len(text)
        return len(text)
    def flush(self):
        pass
    def value(self):
        return ''.join(self.parts) + ('\n[Output truncated]' if self.size > 100000 else '')

def no_input(*args):
    raise RuntimeError('Interactive input() is not supported. Assign a value in a cell instead.')
namespace['input'] = no_input
for line in sys.stdin:
    started = time.monotonic()
    out, err = Output(), Output()
    result = {'stdout': '', 'stderr': '', 'images': []}
    try:
        message = json.loads(line)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            tree = ast.parse(message['code'], filename='<cell>', mode='exec')
            last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
            exec(compile(tree, '<cell>', 'exec'), namespace)
            if last:
                value = eval(compile(ast.Expression(last.value), '<cell>', 'eval'), namespace)
                if value is not None:
                    print(repr(value))
            if 'matplotlib.pyplot' in sys.modules:
                plt = sys.modules['matplotlib.pyplot']
                for number in plt.get_fignums()[:8]:
                    buffer = io.BytesIO()
                    plt.figure(number).savefig(buffer, format='png', dpi=110, bbox_inches='tight')
                    result['images'].append('data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode())
                plt.close('all')
    except BaseException:
        result['error'] = traceback.format_exc(limit=8)
    result.update(stdout=out.value(), stderr=err.value(), durationMs=round((time.monotonic()-started)*1000))
    protocol.write(json.dumps(result) + '\n')
