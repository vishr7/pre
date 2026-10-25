import { useRef, useState } from 'react';
import { FileText, Send, X } from 'lucide-react';
import type { Cell } from './api';
export type ImageInstruction = {instruction:string;image:{mimeType:string;data:string}};
export default function ImageCompose({activeCellId,cells,busy,message,onMessage,onSend,onGenerate}:{activeCellId?:string;cells:Cell[];busy:boolean;message:string;onMessage:(text:string)=>void;onSend:()=>void;onGenerate:(id:string,input:ImageInstruction)=>Promise<void>}){
 const [attachment,setAttachment]=useState<ImageInstruction['image']|null>(null);
 const [target,setTarget]=useState('');const [error,setError]=useState('');const [reading,setReading]=useState(false);
 const [sending,setSending]=useState(false);const locked=useRef(false);
 async function attach(file:File){
  if(busy||locked.current)return;
  setError('');
  if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>2000000){setError('Use a PNG, JPEG, or WebP image under 2 MB.');return;}
  locked.current=true;setReading(true);
  try{const data=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});setAttachment({mimeType:file.type,data});setTarget(cells.some(c=>c.id===activeCellId&&c.type==='latex')?activeCellId!:'');}catch{setError('Could not read that image.');}finally{locked.current=false;setReading(false);}
 }
 async function send(){
  if(busy||locked.current)return;
  if(!attachment){if(message.trim())onSend();return;}
  locked.current=true;setSending(true);setError('');
  try{await onGenerate(target,{instruction:message.trim()||'Recreate this screenshot in LaTeX.',image:attachment});setAttachment(null);onMessage('');}catch(e){setError((e as Error).message);}finally{locked.current=false;setSending(false);}
 }
 return <div className="chat-composer" onPaste={event=>{
  const file=Array.from(event.clipboardData.items).find(item=>item.kind==='file'&&item.type.startsWith('image/'))?.getAsFile();
  if(file){event.preventDefault();void attach(file);}
 }}>
 {attachment && <section className="chat-attachment"><div className="image-attachment"><img alt="Attached screenshot" src={`data:${attachment.mimeType};base64,${attachment.data}`}/><button title="Remove screenshot" disabled={busy||sending} onClick={()=>setAttachment(null)}><X size={14}/></button></div><select aria-label="Target LaTeX cell" value={target} disabled={busy||sending} onChange={e=>setTarget(e.target.value)}><option value="">New LaTeX cell</option>{cells.filter(c=>c.type==='latex').map((c,i)=><option key={c.id} value={c.id}>LaTeX cell {i+1}: {c.source.slice(0,30)}</option>)}</select></section>}
 <textarea aria-label="Message PRE Assistant" placeholder="Ask anything, or paste a screenshot…" value={message} disabled={sending} onChange={e=>onMessage(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/>
 {error && <p className="repair-error" role="alert">{error}</p>}
 <div><span><FileText size={11}/>{reading?'Adding screenshot…':attachment?'Screenshot → LaTeX':'Notebook · Paper · Results'}</span><button title="Send message" disabled={busy||reading||sending||(!message.trim()&&!attachment)} onClick={()=>void send()}><Send size={15}/></button></div>
 </div>;
}
