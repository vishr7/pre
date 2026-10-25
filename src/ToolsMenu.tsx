import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Copy, FlaskConical, RefreshCw, ShieldCheck, SquarePen } from 'lucide-react';
const tools = [
 {name:'Review',icon:SquarePen,detail:'Get feedback on your paper'},
 {name:'Literature',icon:FlaskConical,detail:'Find sources and check citations'},
 {name:'Ablations',icon:Copy,detail:'Compare methods and isolate contributions'},
 {name:'Iterate',icon:RefreshCw,detail:'Improve your method from evidence'},
 {name:'Defend',icon:ShieldCheck,detail:'Practice your thesis defense'},
];
export default function ToolsMenu({value,onChange}:{value:string;onChange:(value:string)=>void}){
 const [position,setPosition]=useState<{top:number;left:number}|null>(null);
 const trigger=useRef<HTMLButtonElement>(null);const menu=useRef<HTMLDivElement>(null);
 const active=tools.some(tool=>tool.name===value);
 const close=()=>{setPosition(null);trigger.current?.focus();};
 function open(){const rect=trigger.current!.getBoundingClientRect();setPosition({top:rect.bottom+7,left:Math.max(8,Math.min(rect.left,window.innerWidth-272))});}
 useEffect(()=>{
  if(!position)return;
  const items=menu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]');
  items?.[Math.max(0,tools.findIndex(tool=>tool.name===value))]?.focus();
  const outside=(event:PointerEvent)=>{if(!menu.current?.contains(event.target as Node)&&!trigger.current?.contains(event.target as Node))setPosition(null);};
  const dismiss=()=>setPosition(null);
  document.addEventListener('pointerdown',outside);window.addEventListener('resize',dismiss);window.addEventListener('scroll',dismiss,true);
  return()=>{document.removeEventListener('pointerdown',outside);window.removeEventListener('resize',dismiss);window.removeEventListener('scroll',dismiss,true);};
 },[position,value]);
 return <><button ref={trigger} className={`tools-trigger ${active?'selected':''}`} aria-label="Research tools" aria-haspopup="menu" aria-expanded={!!position} aria-controls={position?'research-tools-menu':undefined} onClick={()=>position?setPosition(null):open()} onKeyDown={event=>{if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();open();}}}>{active?value:'Tools'}<ChevronDown size={14} className={position?'rotated':''}/></button>{position&&createPortal(<div ref={menu} id="research-tools-menu" role="menu" aria-label="Research tools" className="research-tools-menu" style={position} onKeyDown={event=>{
 if(event.key==='Escape'){event.preventDefault();close();return;}
 if(event.key==='Tab'){setPosition(null);trigger.current?.focus();return;}
 const items=Array.from(menu.current!.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'));
 const index=items.indexOf(document.activeElement as HTMLButtonElement);
 const next=event.key==='ArrowDown'?(index+1)%items.length:event.key==='ArrowUp'?(index-1+items.length)%items.length:event.key==='Home'?0:event.key==='End'?items.length-1:-1;
 if(next>=0){event.preventDefault();items[next].focus();}
 }}><div className="tools-menu-label">RESEARCH TOOLS</div>{tools.map(({name,icon:Icon,detail})=><button key={name} role="menuitem" className={name===value?'chosen':''} onClick={()=>{onChange(name);close();}}><span className="tool-menu-icon"><Icon size={17}/></span><span className="tool-menu-copy"><strong>{name}</strong><small>{detail}</small></span>{name===value&&<Check size={14}/>}</button>)}</div>,document.body)}</>;
}
