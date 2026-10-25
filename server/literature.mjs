const plain=value=>String(value||'').replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim();
export async function searchLiterature({query},fetchImpl=fetch){
 if(typeof query!=='string'||query.trim().length<3||query.length>500)throw new Error('Enter a topic or DOI between 3 and 500 characters.');
 const url=new URL('https://api.crossref.org/works');url.searchParams.set('query.bibliographic',query.trim());url.searchParams.set('rows','8');
 const response=await fetchImpl(url,{headers:{Accept:'application/json','User-Agent':'PRE-Research/0.1'},signal:AbortSignal.timeout(20000)});
 if(!response.ok)throw new Error(`Literature search unavailable (Crossref HTTP ${response.status}). Try again shortly.`);
 const data=await response.json();
 if(!Array.isArray(data.message?.items))throw new Error('Literature service returned an invalid response.');
 return {query:query.trim(),provider:'Crossref',searchedAt:new Date().toISOString(),papers:data.message.items.filter(x=>typeof x.DOI==='string').map(x=>({doi:x.DOI,title:plain(x.title?.[0]),authors:(x.author||[]).slice(0,8).map(a=>plain([a.given,a.family].filter(Boolean).join(' '))),year:x.published?.['date-parts']?.[0]?.[0]||null,venue:plain(x['container-title']?.[0]),url:'https://doi.org/'+encodeURIComponent(x.DOI),abstract:plain(x.abstract).slice(0,8000),evidence:x.abstract?'metadata and abstract':'metadata only'}))};
}
export async function verifyDOIs({dois},fetchImpl=fetch){
 if(!Array.isArray(dois)||dois.length>12||dois.some(d=>typeof d!=='string'||d.length>250||!/^10\.\d{4,9}\/\S+$/.test(d)))throw new Error('Provide up to 12 valid DOI identifiers.');
 return {records:await Promise.all([...new Set(dois)].map(async doi=>{
  try{
   const r=await fetchImpl('https://api.crossref.org/works/'+encodeURIComponent(doi),{headers:{Accept:'application/json'},signal:AbortSignal.timeout(12000)});
   if(r.status===404)return {doi,status:'not-found',message:'Not found in Crossref; other registries may hold this DOI.'};
   if(!r.ok)return {doi,status:'unavailable',message:`Crossref HTTP ${r.status}`};
   const data=await r.json();
   if(String(data.message?.DOI).toLowerCase()!==doi.toLowerCase())return {doi,status:'unavailable',message:'Registry response did not match the requested DOI.'};
   return {doi,status:'registered',title:plain(data.message.title?.[0])};
  }catch{return {doi,status:'unavailable',message:'Registry could not be reached. Try again.'};}
 }))};
}
