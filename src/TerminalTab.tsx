import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { request } from './api';
import { RemoteCapture, maxRemoteCodeBytes, remoteRunCommand, type RemoteResult } from './remoteRun';

const remoteStartTimeoutMs = 15000;
const theme = {background:'#fdfafb',foreground:'#534552',cursor:'#b77691',cursorAccent:'#fdfafb',selectionBackground:'#edd6e2',black:'#514450',red:'#af506a',green:'#53846c',yellow:'#94743c',blue:'#5d7eaa',magenta:'#a26494',cyan:'#528c8e',white:'#a79ba6',brightBlack:'#948391',brightRed:'#c46d86',brightGreen:'#67987f',brightYellow:'#ac8a4a',brightBlue:'#7898bd',brightMagenta:'#b783aa',brightCyan:'#70a3a5',brightWhite:'#d4c9d1'};

/** What the panel can do with one terminal tab. */
export type TabHandle = {
  connect(command: string): void;      // type a command now, or after (re)starting the shell
  clear(): void;
  restart(): void;
  runRemote(code: string, interpreter: string): Promise<RemoteResult>;
};

type Props = {
  sessionId: string;
  terminalId: string;
  shown: boolean;                       // panel expanded and this tab selected
  initialCommand?: string;              // e.g. a saved ssh command for a new tab
  onStatus(status: string): void;
  register(handle: TabHandle | null): void;
};

/** One shell: its own xterm, WebSocket and "Run on SSH" capture. Stays mounted while hidden. */
export default function TerminalTab({ sessionId, terminalId, shown, initialCommand, onStatus, register }: Props) {
  const [generation, setGeneration] = useState(0);
  const host = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal | null>(null);
  const fit = useRef<FitAddon | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const pending = useRef<string | null>(initialCommand ?? null); // command to type once the shell is ready
  // The cell currently running over SSH in this tab; its output is captured from the terminal stream.
  const remote = useRef<{ capture: RemoteCapture; resolve: (r: RemoteResult) => void; reject: (e: Error) => void; timer: number } | null>(null);
  const status = useRef(onStatus); status.current = onStatus;

  function finishRemote(result: RemoteResult) {
    const active=remote.current;if(!active)return;
    remote.current=null;clearTimeout(active.timer);active.resolve(result);
  }
  function failRemote(message: string) {
    const active=remote.current;if(!active)return;
    remote.current=null;clearTimeout(active.timer);active.reject(new Error(message));
  }
  const send = (data: string) => {
    if(socket.current?.readyState !== WebSocket.OPEN)return false;
    socket.current.send(JSON.stringify({type:'input',data}));return true;
  };

  useEffect(() => {
    if (!host.current) return;
    let disposed = false;
    status.current('Connecting…');
    const term = new Terminal({ cursorBlink:true, screenReaderMode:true, fontSize:12, fontFamily:'Menlo, Monaco, monospace', scrollback:3000, theme });
    const addon = new FitAddon(); term.loadAddon(addon);term.open(host.current);terminal.current=term;fit.current=addon;
    const resize = () => {
      if(!host.current?.clientHeight || !host.current?.clientWidth)return;
      addon.fit();
      if(socket.current?.readyState === WebSocket.OPEN)socket.current.send(JSON.stringify({type:'resize',cols:term.cols,rows:term.rows}));
    };
    const observer=new ResizeObserver(resize);observer.observe(host.current);resize();
    const input=term.onData(data => {
      send(data);
      // Ctrl+C aborts the whole remote command line, so the end marker will never arrive.
      if(data.includes('\x03'))finishRemote({output:'',exitCode:null,cancelled:true});
    });
    const decoder=new TextDecoder();
    void request<{path:string}>('', '/api/terminal/open', {sessionId,terminalId}).then(({path}) => {
      if(disposed)return;
      const url=new URL(path,window.location.href);url.protocol=url.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws=new WebSocket(url);socket.current=ws;
      ws.onopen=() => {
        if(disposed){ws.close();return;}
        status.current('Local shell');resize();term.focus();
        const command=pending.current;pending.current=null;
        // Give the shell a moment to print its prompt before typing a saved ssh command.
        if(command)setTimeout(() => {if(!disposed && ws.readyState === WebSocket.OPEN)ws.send(JSON.stringify({type:'input',data:`${command}\r`}));}, 700);
      };
      ws.onmessage=event => {
        if(disposed)return;
        const message=JSON.parse(event.data);
        if(message.type === 'output'){
          const bytes=Uint8Array.from(atob(message.data),c=>c.charCodeAt(0));
          term.write(bytes);
          const result=remote.current?.capture.feed(decoder.decode(bytes,{stream:true}));
          if(result)finishRemote(result);
        } else if(message.type === 'exit' || message.type === 'error'){
          failRemote('The terminal closed before the cell finished.');
          status.current(message.type === 'error' ? 'Connection failed' : 'Exited');
          term.writeln(`\r\n${message.message}\r\nUse Restart terminal to open a new shell.`);
        }
      };
      ws.onclose=() => {failRemote('The terminal disconnected before the cell finished.');if(!disposed)status.current('Disconnected · restart to reconnect');};
      ws.onerror=() => {if(!disposed){status.current('Connection failed');term.writeln('\r\nCould not connect to the local terminal. Start the app with npm run dev.');}};
    }).catch(error => {if(!disposed){status.current('Connection failed');term.writeln(`\r\n${(error as Error).message}`);}});
    return () => {disposed=true;failRemote('The terminal was closed.');observer.disconnect();input.dispose();socket.current?.close();socket.current=null;term.dispose();terminal.current=null;fit.current=null;};
  }, [generation,sessionId,terminalId]);

  // Hidden tabs have no size; refit and focus when this one is shown again.
  useEffect(() => {
    if(!shown)return;
    requestAnimationFrame(() => {
      fit.current?.fit();
      const term=terminal.current;
      if(term && socket.current?.readyState === WebSocket.OPEN)socket.current.send(JSON.stringify({type:'resize',cols:term.cols,rows:term.rows}));
      term?.focus();
    });
  }, [shown]);

  useEffect(() => {
    register({
      connect(command) {
        if(send(`${command}\r`))terminal.current?.focus();
        else {pending.current=command;setGeneration(value=>value+1);}
      },
      clear() {terminal.current?.clear();},
      restart() {setGeneration(value=>value+1);},
      runRemote(code, interpreter) {
        if(socket.current?.readyState !== WebSocket.OPEN)return Promise.reject(new Error('Open the terminal and connect with SSH first (SSH ▾ in the terminal bar).'));
        if(remote.current)return Promise.reject(new Error('Another cell is already running in this terminal. Wait for it, or press Ctrl+C there.'));
        if(new TextEncoder().encode(code).length > maxRemoteCodeBytes)return Promise.reject(new Error('This cell is too large to send over the terminal (256 KB max).'));
        const id=crypto.randomUUID().replace(/-/g,'').slice(0,12);
        return new Promise<RemoteResult>((resolve,reject) => {
          const capture=new RemoteCapture(id);
          // If nothing starts, the terminal is probably not a Linux shell (e.g. still local PowerShell).
          const timer=window.setTimeout(() => {
            if(remote.current?.capture === capture && !capture.started)failRemote('No response from the terminal. Make sure it is logged into a Linux machine over SSH (not the local shell).');
          }, remoteStartTimeoutMs);
          remote.current={capture,resolve,reject,timer};
          send(`${remoteRunCommand(code,id,interpreter)}\r`);
        });
      },
    });
    return () => register(null);
  }, []);

  return <div ref={host} className="terminal-screen" style={{display:shown?'block':'none'}}/>;
}
