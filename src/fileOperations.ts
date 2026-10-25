import type {Workspace} from './projectSync.ts';
import {linkFiles} from './projectSync.ts';
export function validProjectPath(value:string){
 const path=value.trim();
 if(!path||path.startsWith('/')||path.includes('\\')||/[\x00-\x1f{}%#]/.test(path)||path.split('/').some(p=>!p||p==='.'||p==='..'))throw new Error('Use a relative file path, for example sections/methods.tex.');
 return path;
}
const normalize=(value:string)=>{const parts:string[]=[];for(const p of value.split('/')){if(p==='..')parts.pop();else if(p&&p!=='.')parts.push(p);}return parts.join('/');};
const directory=(path:string)=>path.split('/').slice(0,-1).join('/');
function relative(from:string,to:string){const a=directory(from).split('/').filter(Boolean),b=to.split('/');while(a.length&&b.length&&a[0]===b[0]){a.shift();b.shift();}return [...a.map(()=>'..'),...b].join('/');}
export function moveProjectFile(state:Workspace,from:string,target:string):Workspace{
 const to=validProjectPath(target);
 if(from===to)return state;
 if(!state.files.some(f=>f.path===from))throw new Error('That file no longer exists.');
 if(state.files.some(f=>f.path===to))throw new Error('A file already exists there. Choose another name.');
 if(state.files.some(f=>f.path.startsWith(to+'/')||to.startsWith(f.path+'/')))throw new Error('A file and a folder cannot share the same path.');
 const known=new Set(state.files.map(f=>f.path));
 function rewrite(source:string,oldPath:string,newPath:string){
 return source.split('\n').map(line=>{
  const at=line.search(/(?<!\\)%/);const code=at<0?line:line.slice(0,at),comment=at<0?'':line.slice(at);
  return code.replace(/\\(input|include|includegraphics|bibliography|addbibresource)(\*?(?:\s*\[[^\]]*\])?\s*)\{([^}]+)\}/g,(all,command:string,options:string,value:string)=>{
   const replacements=(command==='bibliography'?value.split(','):[value]).map((raw:string)=>{
    const name=raw.trim();if(name.includes('\\')||name.includes('://'))return raw;
    const extension=['input','include'].includes(command)?'.tex':['bibliography','addbibresource'].includes(command)?'.bib':'';
    const names=[name,...extension&&!name.endsWith(extension)?[name+extension]:[]];
    const candidates=names.map(n=>normalize(directory(oldPath)+'/'+n)).concat(names.map(normalize));
    const resolved=candidates.find(p=>known.has(p));
    if(!resolved)return raw;
    if(resolved!==from&&oldPath===newPath)return raw;
    const destination=resolved===from?to:resolved;
    let updated=['input','include'].includes(command)?relative(newPath,destination):destination;
    if(extension&&!name.endsWith(extension)&&updated.endsWith(extension))updated=updated.slice(0,-extension.length);
    return updated;
   });
   return `\\${command}${options}{${replacements.join(',')}}`;
  })+comment;
 }).join('\n');
 }
 const files=state.files.map(f=>{const path=f.path===from?to:f.path;return {...f,path,content:f.path.endsWith('.tex')?rewrite(f.content,f.path,path):f.content};});
 const cells=state.cells.map(c=>({...c,...c.filePath===from?{filePath:to}:{},...c.type==='latex'&&!c.filePath?{source:rewrite(c.source,'main.tex','main.tex')}: {}}));
 return linkFiles(cells,files);
}
