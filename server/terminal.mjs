import { WebSocketServer, WebSocket } from 'ws';
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const cwd = fileURLToPath(new URL('../', import.meta.url));
const worker = fileURLToPath(new URL('./terminal-worker.py', import.meta.url));
export function terminalService(server, runtime) {
  const sockets = new WebSocketServer({ noServer: true, maxPayload: 65536, perMessageDeflate: false });
  const tickets = new Map();
  const sessions = new Map();
  function stop(sessionId) {
    const active = sessions.get(sessionId);
    if (!active) return;
    sessions.delete(sessionId);
    active.socket?.close(1000, 'Terminal closed');
    active.child?.stdin.end();
    const timer = setTimeout(() => active.child?.kill('SIGTERM'), 1000); timer.unref();
  }
  const sweep = setInterval(() => { for (const [token, ticket] of tickets) if (ticket.expires < Date.now()) tickets.delete(token); }, 30000);
  sweep.unref();
  function upgrade(req, socket, head) {
    if (!req.url?.startsWith('/__pre_terminal/')) return;
    const host = req.headers.host || '';
    const token = req.url.slice('/__pre_terminal/'.length);
    const ticket = tickets.get(token);
    if (!/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host) || req.headers.origin !== `http://${host}` || !ticket || ticket.expires < Date.now()) {
      socket.write('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'); socket.destroy(); return;
    }
    tickets.delete(token);
    if (!runtime.sessions.has(ticket.sessionId)) {socket.destroy();return;}
    stop(ticket.sessionId);
    sockets.handleUpgrade(req, socket, head, ws => {
      const child = spawn(runtime.python, [worker], { cwd, detached: true, stdio: ['pipe', 'ignore', 'pipe', 'pipe'], env: {...process.env, TERM:'xterm-256color', PYTHONUNBUFFERED:'1'} });
      const active = { child, socket:ws };
      sessions.set(ticket.sessionId, active);
      let buffer = '', error = '';
      const send = message => { if(ws.readyState === WebSocket.OPEN)ws.send(JSON.stringify(message)); };
      child.stdin.on('error', () => {});
      child.stderr.on('data', data => {error=(error+data).slice(-4000);});
      child.stdio[3].on('data', data => {
        buffer += data;
        let end;
        while ((end=buffer.indexOf('\n')) !== -1) {
          const line=buffer.slice(0,end);buffer=buffer.slice(end+1);
          try {send(JSON.parse(line));} catch {}
        }
        // Bound browser-side backpressure instead of buffering unlimited command output.
        if(ws.bufferedAmount > 4000000)stop(ticket.sessionId);
      });
      child.on('error', err => {send({type:'error',message:`Could not start local shell: ${err.message}`});ws.close();});
      child.on('exit', code => {
        if(sessions.get(ticket.sessionId) === active)sessions.delete(ticket.sessionId);
        send({type:'exit',message:error || `Shell exited${code === null ? '' : ` (${code})`}.`});ws.close();
      });
      ws.on('message', data => {
        try {
          const message=JSON.parse(data.toString());
          if(message.type === 'input' && typeof message.data === 'string' && message.data.length <= 32768)child.stdin.write(JSON.stringify(message)+'\n');
          else if(message.type === 'resize' && Number.isInteger(message.cols) && Number.isInteger(message.rows))child.stdin.write(JSON.stringify(message)+'\n');
        } catch {ws.close(1008,'Invalid terminal message');}
      });
      ws.on('close', () => {if(sessions.get(ticket.sessionId) === active)stop(ticket.sessionId);});
      ws.on('error', () => {if(sessions.get(ticket.sessionId) === active)stop(ticket.sessionId);});
      send({type:'ready'});
    });
  }
  server.httpServer?.on('upgrade', upgrade);
  server.httpServer?.once('close', () => {
    clearInterval(sweep);for(const id of sessions.keys())stop(id);tickets.clear();sockets.close();
  });
  return {
    async open({sessionId}) {
      if(process.platform === 'win32')throw new Error('The local terminal currently requires macOS or Linux.');
      await runtime.session(sessionId);
      for(const [token,ticket] of tickets)if(ticket.sessionId === sessionId)tickets.delete(token);
      const token=randomBytes(32).toString('hex');tickets.set(token,{sessionId,expires:Date.now()+30000});
      return {path:`/__pre_terminal/${token}`};
    },
    close({sessionId}) {stop(sessionId);for(const [token,ticket] of tickets)if(ticket.sessionId === sessionId)tickets.delete(token);return {ok:true};},
  };
}
