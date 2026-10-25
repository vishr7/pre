import {useState,type ComponentProps,type MutableRefObject} from 'react';
import type { RemoteRunner } from './remoteRun';
import LocalIteratePanel from './LocalIteratePanel';
import BackendIteratePanel from './BackendIteratePanel';
export default function IteratePanel({base,runner,...props}:ComponentProps<typeof LocalIteratePanel>&{base:string;runner?:MutableRefObject<RemoteRunner|null>}){
 const [backend,setBackend]=useState(false);
 return <><div className="add-toolbar"><button onClick={()=>setBackend(false)} aria-pressed={!backend}>AI parameter batch</button><button onClick={()=>setBackend(true)} aria-pressed={backend}>Backend / SSH study</button></div><div hidden={backend}><LocalIteratePanel {...props}/></div><div hidden={!backend}><BackendIteratePanel base={base} files={props.files} runner={runner}/></div></>;
}
