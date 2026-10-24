import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { ChevronDown, ChevronUp, RotateCcw, TerminalSquare, Trash2 } from 'lucide-react';
import { request } from './api';
import '@xterm/xterm/css/xterm.css';

export default function TerminalPanel({ sessionId }: { sessionId: string }) {
  const [visible, setVisible] = useState(true);
  const [started, setStarted] = useState(true);
  const [generation, setGeneration] = useState(0);
  const [status, setStatus] = useState('');
  const [height, setHeight] = useState(200);
  const host = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal | null>(null);
  const fit = useRef<FitAddon | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const drag = useRef<{y:number;height:number} | null>(null);
  useEffect(() => {
    if (!started || !host.current) return;
    let disposed = false;
    setStatus('Connecting…');
    const term = new Terminal({ cursorBlink:true, screenReaderMode:true, fontSize:12, fontFamily:'Menlo, Monaco, monospace', scrollback:3000,
      theme:{background:'#fdfafb',foreground:'#534552',cursor:'#b77691',cursorAccent:'#fdfafb',selectionBackground:'#edd6e2',black:'#514450',red:'#af506a',green:'#53846c',yellow:'#94743c',blue:'#5d7eaa',magenta:'#a26494',cyan:'#528c8e',white:'#a79ba6',brightBlack:'#948391',brightRed:'#c46d86',brightGreen:'#67987f',brightYellow:'#ac8a4a',brightBlue:'#7898bd',brightMagenta:'#b783aa',brightCyan:'#70a3a5',brightWhite:'#d4c9d1'},
    });
    const addon = new FitAddon(); term.loadAddon(addon);term.open(host.current);terminal.current=term;fit.current=addon;
    const resize = () => {
      if(!host.current?.clientHeight || !host.current?.clientWidth)return;
      addon.fit();
      if(socket.current?.readyState === WebSocket.OPEN)socket.current.send(JSON.stringify({type:'resize',cols:term.cols,rows:term.rows}));
    };
    const observer=new ResizeObserver(resize);observer.observe(host.current);resize();
    const input=term.onData(data => {if(socket.current?.readyState === WebSocket.OPEN)socket.current.send(JSON.stringify({type:'input',data}));});
    void request<{path:string}>('', '/api/terminal/open', {sessionId}).then(({path}) => {
      if(disposed)return;
      const url=new URL(path,window.location.href);url.protocol=url.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws=new WebSocket(url);socket.current=ws;
      ws.onopen=() => {if(disposed){ws.close();return;}setStatus('Local shell');resize();term.focus();};
      ws.onmessage=event => {
        if(disposed)return;
        const message=JSON.parse(event.data);
        if(message.type === 'output')term.write(Uint8Array.from(atob(message.data),c=>c.charCodeAt(0)));
        else if(message.type === 'exit' || message.type === 'error'){setStatus(message.type === 'error' ? 'Connection failed' : 'Exited');term.writeln(`\r\n${message.message}\r\nUse Restart terminal to open a new shell.`);}
      };
      ws.onclose=() => {if(!disposed)setStatus(current => current === 'Local shell' || current === 'Connecting…' ? 'Disconnected · restart to reconnect' : current);};
      ws.onerror=() => {if(!disposed){setStatus('Connection failed');term.writeln('\r\nCould not connect to the local terminal. Start the app with npm run dev.');}};
    }).catch(error => {if(!disposed){setStatus('Connection failed');term.writeln(`\r\n${(error as Error).message}`);}});
    return () => {disposed=true;observer.disconnect();input.dispose();socket.current?.close();socket.current=null;term.dispose();terminal.current=null;fit.current=null;};
  }, [started,generation,sessionId]);
  useEffect(() => {if(visible){fit.current?.fit();terminal.current?.focus();}}, [visible]);
  function toggle() {setVisible(value=>!value);setStarted(true);}
  return <section className={`terminal-panel ${visible ? 'expanded' : ''}`} style={{height:visible ? height : 34}} aria-label="Local terminal">
    {visible && <div className="terminal-resize" role="separator" aria-label="Resize terminal" aria-orientation="horizontal" aria-valuenow={height} aria-valuemin={140} aria-valuemax={600} tabIndex={0}
      onPointerDown={event=>{event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);drag.current={y:event.clientY,height};}}
      onPointerMove={event=>{if(drag.current)setHeight(Math.max(140,Math.min(600,window.innerHeight-180,drag.current.height+drag.current.y-event.clientY)));}}
      onPointerUp={event=>{drag.current=null;event.currentTarget.releasePointerCapture(event.pointerId);}}
      onPointerCancel={()=>{drag.current=null;}}
      onKeyDown={event=>{if(event.key==='ArrowUp'||event.key==='ArrowDown'){event.preventDefault();setHeight(value=>Math.max(140,Math.min(600,value+(event.key==='ArrowUp'?20:-20))));}}}/>} 
    <div className="terminal-heading"><button className="terminal-toggle" onClick={toggle} aria-expanded={visible}><TerminalSquare size={14}/> Terminal {visible ? <ChevronDown size={13}/> : <ChevronUp size={13}/>}</button>{started && <span className="terminal-status" role="status">{status}</span>}<span className="spacer"/>{visible && <><span className="terminal-hint">Local shell · SSH supported</span><button className="icon-btn" title="Clear terminal" onClick={()=>terminal.current?.clear()}><Trash2 size={13}/></button><button className="icon-btn" title="Restart terminal" onClick={()=>setGeneration(value=>value+1)}><RotateCcw size={13}/></button></>}</div>
    <div ref={host} className="terminal-screen" style={{display:visible?'block':'none'}}/>
  </section>;
}
