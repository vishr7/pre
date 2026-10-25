import {useState,useEffect,type ComponentProps} from 'react';
import LocalIteratePanel from './LocalIteratePanel';
import BackendIteratePanel from './BackendIteratePanel';
export default function IteratePanel({base,...props}:ComponentProps<typeof LocalIteratePanel>&{base:string}){
 const [backend,setBackend]=useState(false);
 useEffect(()=>{if(props.workflow)setBackend(false);},[props.workflow?.id]);
 return <div className="iterate-workspace"><div className="add-toolbar"><button onClick={()=>setBackend(false)} aria-pressed={!backend}>Simple tests</button><button onClick={()=>setBackend(true)} aria-pressed={backend}>Advanced · cluster studies</button></div><div className="iterate-scroll" role="region" aria-label="AI parameter batch" tabIndex={0} hidden={backend}><LocalIteratePanel {...props}/></div><div className="iterate-scroll" role="region" aria-label="Backend study" tabIndex={0} hidden={!backend}><BackendIteratePanel base={base} files={props.files}/></div></div>;
}
