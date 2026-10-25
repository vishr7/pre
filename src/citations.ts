import type {Cell,ProjectFile} from './api';
export function citationAudit(files:ProjectFile[],cells:Cell[]){
 const strip=(s:string)=>s.replace(/(?<!\\)%[^\n]*/g,'');
 const latex=[...files.filter(f=>f.path.endsWith('.tex')).map(f=>f.content),...cells.filter(c=>c.type==='latex'&&!c.filePath).map(c=>c.source)].map(strip).join('\n');
 const cited=[...new Set([...latex.matchAll(/\\(?:[a-zA-Z]*cite[a-zA-Z]*|nocite)\*?(?:\s*\[[^\]]*\])*\s*\{([^}]+)\}/g)].flatMap(m=>m[1].split(',').map(k=>k.trim())).filter(k=>k&&k!=='*'))];
 const definitions=[...files.filter(f=>f.path.endsWith('.bib')).flatMap(f=>[...strip(f.content).matchAll(/@(?!comment\b|string\b|preamble\b)\w+\s*[{(]\s*([^,\s]+)\s*,/gi)].map(m=>m[1])),...[...latex.matchAll(/\\bibitem(?:\[[^\]]*\])?\s*\{([^}]+)\}/g)].map(m=>m[1])];
 const defined=new Set(definitions);
 const dois=[...new Set(files.filter(f=>f.path.endsWith('.bib')).flatMap(f=>[...strip(f.content).matchAll(/\bdoi\s*=\s*[\{"]([^\}"]+)[\}"]/gi)].map(m=>m[1].trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,''))))];
 return {dois,cited,missing:cited.filter(k=>!defined.has(k)),unused:[...defined].filter(k=>!cited.includes(k)),duplicates:[...defined].filter(k=>definitions.filter(x=>x===k).length>1),scope:'Static citation-key check only. Does not verify source existence, bibliography compilation, or whether a source supports a claim.'};
}
