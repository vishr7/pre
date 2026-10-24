import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown } from 'lucide-react';
const tools = [
 {name:'generic',label:'General',detail:'Broad research feedback'},
 {name:'neurips',label:'NeurIPS',detail:'Machine learning research'},
 {name:'acl',label:'ACL',detail:'Language and NLP research'},
 {name:'journal',label:'Journal',detail:'Journal submission review'},
];
export default function VenueMenu({value,onChange,disabled=false}:{value:string;onChange:(value:string)=>void;disabled?:boolean}){
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
 return <><button ref={trigger} disabled={disabled} className={`tools-trigger venue-trigger ${active?'selected':''}`} aria-label="Review venue" aria-haspopup="menu" aria-expanded={!!position} aria-controls={position?'review-venue-menu':undefined} onClick={()=>position?setPosition(null):open()} onKeyDown={event=>{if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();open();}}}>{tools.find(tool=>tool.name===value)?.label || 'General'}<ChevronDown size={14} className={position?'rotated':''}/></button>{position&&createPortal(<div ref={menu} id="review-venue-menu" role="menu" aria-label="Review venue" className="research-tools-menu venue-menu" style={position} onKeyDown={event=>{
 if(event.key==='Escape'){event.preventDefault();close();return;}
 if(event.key==='Tab'){setPosition(null);trigger.current?.focus();return;}
 const items=Array.from(menu.current!.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'));
 const index=items.indexOf(document.activeElement as HTMLButtonElement);
 const next=event.key==='ArrowDown'?(index+1)%items.length:event.key==='ArrowUp'?(index-1+items.length)%items.length:event.key==='Home'?0:event.key==='End'?items.length-1:-1;
 if(next>=0){event.preventDefault();items[next].focus();}
 }}><div className="tools-menu-label">REVIEW VENUE</div>{tools.map(({name,label,detail})=><button key={name} role="menuitem" aria-current={name===value ? true : undefined} className={name===value?'chosen':''} onClick={()=>{onChange(name);close();}}><span className="tool-menu-copy"><strong>{label}</strong><small>{detail}</small></span>{name===value&&<Check size={14}/>}</button>)}</div>,document.body)}</>;
}
