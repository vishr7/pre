import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

test('Local terminal provides a real TTY, executes commands, resizes, and exits', {skip:process.platform==='win32'}, async () => {
 const worker=spawn('python3',[fileURLToPath(new URL('./terminal-worker.py',import.meta.url))],{detached:true,stdio:['pipe','ignore','pipe','pipe'],env:{...process.env,SHELL:'/bin/sh'}});
 let output='',buffer='',errors='';
 worker.stderr.on('data',chunk=>{errors+=chunk;});
 worker.stdio[3].on('data',chunk=>{
   buffer+=chunk;
   let end;
   while((end=buffer.indexOf('\n'))!==-1){
     const message=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);
     if(message.type==='output')output+=Buffer.from(message.data,'base64').toString();
   }
 });
 const completion=new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>{worker.kill('SIGTERM');reject(new Error('PTY test timed out'));},10000);
   worker.on('error',error=>{clearTimeout(timer);reject(error);});
   worker.on('exit',code=>{clearTimeout(timer);code===0?resolve():reject(new Error(errors || `Terminal exited with ${code}`));});
 });
 worker.stdin.write(JSON.stringify({type:'resize',cols:100,rows:32})+'\n');
 worker.stdin.write(JSON.stringify({type:'input',data:"printf '\\nRESULT=%s\\n' $((6 * 7)); tty; stty size; exit\r"})+'\n');
 await completion;
 assert.match(output,/RESULT=42/);
 assert.match(output,/\/dev\/(tty|pts)/);
 assert.match(output,/32 100/);
});
