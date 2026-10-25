import type {Workspace} from './projectSync.ts';
import {linkFiles} from './projectSync.ts';
import {paperLatex} from './latexSource.ts';
import {formatPaper} from './paperFormat.ts';

// Only split top-level section commands; never split commands inside a macro,
// equation, figure, table, or verbatim environment.
export function sectionOffsets(source:string){
 const offsets:number[]=[];let depth=0;const environments:string[]=[];
 for(let i=0;i<source.length;i++){
  if(source[i]==='%'){const end=source.indexOf('\n',i);i=end<0?source.length:end;continue;}
  if(source[i]==='\\'){
   const env=/^\\(begin|end)\{([^}]+)\}/.exec(source.slice(i));
   if(env){if(env[1]==='begin')environments.push(env[2]);else environments.pop();i+=env[0].length-1;continue;}
   if(!depth&&!environments.length&&/^\\section\*?(?:\[|\{)/.test(source.slice(i)))offsets.push(i);
   const command=/^\\(?:[A-Za-z]+|.)/.exec(source.slice(i));if(command)i+=command[0].length-1;
  }else if(source[i]==='{')depth++;else if(source[i]==='}')depth--;
 }
 return offsets;
}
export function organizeManuscript(state:Workspace):Workspace{
 const source=formatPaper(paperLatex(state.files,state.cells));
 const begin=source.indexOf('\\begin{document}'),end=source.lastIndexOf('\\end{document}');
 if(begin<0||end<begin)throw new Error('Close the document before organizing sections.');
 const bodyStart=begin+'\\begin{document}'.length;
 const body=source.slice(bodyStart,end);const offsets=sectionOffsets(body);
 if(!offsets.length)throw new Error('Add a \\section{Title} heading first, then organize the manuscript.');
 const backup={path:`history/manuscript-${crypto.randomUUID()}.json`,content:JSON.stringify(state,null,2)};
 const sections=offsets.map((start,index)=>{
  const content=body.slice(start,offsets[index+1]??body.length);
  const title=/^\\section\*?(?:\[[^\]]*\])?\{([^}]+)\}/.exec(content)?.[1]||'section';
  const slug=title.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,50)||'section';
  return {path:`sections/${String(index+1).padStart(2,'0')}-${slug}.tex`,content};
 });
 const main=source.slice(0,bodyStart)+body.slice(0,offsets[0])+sections.map(f=>`\\input{${f.path}}\n`).join('')+source.slice(end);
 // A recovery snapshot preserves original paths, sources, outputs and cell IDs.
 const files=[...state.files.filter(f=>!f.path.endsWith('.tex')),backup,{path:'main.tex',content:main},...sections];
 return linkFiles(state.cells.filter(c=>c.type!=='latex'),files);
}
export function addSection(state:Workspace,title='New section'):Workspace{
 const slug=title.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')||'section';
 let n=1,path=`sections/${slug}.tex`;while(state.files.some(f=>f.path===path)){path=`sections/${slug}-${++n}.tex`;}
 const root=state.files.find(f=>f.path==='main.tex')||state.files.find(f=>f.path==='paper/main.tex')||state.files.find(f=>/\\begin\{document\}/.test(f.content)&&f.path.endsWith('.tex'));
 const file={path,content:`\\section{${title.replace(/[\\{}%]/g,'')}}\n% Write this section here.\n`};
 const input='../'.repeat((root?.path.split('/').length||1)-1)+path;
 const files=state.files.map(f=>f===root&&f.content.includes('\\end{document}')?{...f,content:f.content.replace('\\end{document}',`\\input{${input}}\n\\end{document}`)}:f);
 return linkFiles(state.cells,[...files,file]);
}
