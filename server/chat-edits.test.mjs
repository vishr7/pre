import test from 'node:test';
import assert from 'node:assert/strict';
import {validateChatEdits} from './ai/chat-edits.mjs';
import {prepareChatEdits,patchedSources} from '../src/chatEdits.ts';
test('page break edits original abstract without duplicating or losing following content',()=>{
 const source='Title\n\\begin{abstract}\nAn abstract.\n\\end{abstract}\n\\section{Introduction}\nText';
 const cells=[{id:'latex',type:'latex',source}];
 const edits=[{target:'cell',id:'latex',old_text:'\\begin{abstract}',new_text:'\\clearpage\n\\begin{abstract}',reason:'Start abstract and following material on a new page'}];
 validateChatEdits(edits,{notebook:cells});
 const modified=patchedSources(prepareChatEdits(edits,cells,[]),cells,[])['cell:latex'];
 assert.equal(modified.match(/begin\{abstract\}/g).length,1);assert.ok(modified.endsWith('\\section{Introduction}\nText'));assert.ok(modified.includes('\\clearpage\n\\begin{abstract}'));
});
test('moves remove the old location and update both targets together',()=>{
 const cells=[{id:'a',type:'markdown',source:'Intro\nMove this.'},{id:'b',type:'markdown',source:'Conclusion'}];
 const edits=[{target:'cell',id:'a',old_text:'\nMove this.',new_text:'',reason:'Move'},{target:'cell',id:'b',old_text:'Conclusion',new_text:'Conclusion\nMove this.',reason:'Move'}];
 validateChatEdits(edits,{notebook:cells});
 const proposal=prepareChatEdits(edits,cells,[]);const result=patchedSources(proposal,cells,[]);
 assert.equal(result['cell:a'],'Intro');assert.equal(result['cell:b'],'Conclusion\nMove this.');
 assert.throws(()=>patchedSources(proposal,[{...cells[0],source:'User change'},cells[1]],[]),/changed/);
});
test('rejects unknown, ambiguous and overlapping edit targets',()=>{
 const edit={target:'cell',id:'a',old_text:'text',new_text:'new',reason:'Edit'};
 assert.throws(()=>validateChatEdits([edit],{notebook:[]}),/unavailable/);
 assert.throws(()=>validateChatEdits([edit],{notebook:[{id:'a',source:'text text'}]}),/unique/);
 assert.throws(()=>validateChatEdits([edit,edit],{notebook:[{id:'a',source:'text'}]}),/overlap/);
});
test('rejects AI package command typo for LaTeX targets before presenting edits',()=>{
 const context={notebook:[{id:'a',type:'latex',source:'Old source'}]};
 const edit={target:'cell',id:'a',old_text:'Old source',new_text:String.raw`\package[letterpaper,margin=1in]{geometry}`,reason:'Format paper'};
 assert.throws(()=>validateChatEdits([edit],context),/usepackage/);
 assert.doesNotThrow(()=>validateChatEdits([{...edit,new_text:String.raw`\usepackage[letterpaper,margin=1in]{geometry}`}],context));
 assert.doesNotThrow(()=>validateChatEdits([edit],{notebook:[{...context.notebook[0],type:'markdown'}]}));
});
test('mirrors paper changes into matching notebook cells atomically',()=>{
 const source='A shared abstract.\nA shared conclusion.';
 const cells=[{id:'a',type:'latex',source}];
 const files=[{path:'paper/main.tex',content:source}];
 const edits=['abstract','conclusion'].map(word=>({target:'file',id:'paper/main.tex',old_text:`A shared ${word}.`,new_text:`An updated ${word}.`,reason:'Revise'}));
 const proposal=prepareChatEdits(edits,cells,files);
 assert.equal(proposal.edits.length,4);
 const result=patchedSources(proposal,cells,files);
 assert.equal(result['cell:a'],result['file:paper/main.tex']);
 assert.equal(result['cell:a'],'An updated abstract.\nAn updated conclusion.');
 assert.throws(()=>patchedSources(proposal,[{...cells[0],source:'Changed'}],files),/changed/);
});
test('mirrors notebook changes into matching files without changing unrelated cells',()=>{
 const cells=[{id:'a',type:'latex',source:'Shared section text'},{id:'b',type:'latex',source:'Unrelated section'}];
 const files=[{path:'paper/main.tex',content:'Before\nShared section text\nAfter'}];
 const proposal=prepareChatEdits([{target:'cell',id:'a',old_text:'Shared section text',new_text:'Updated section text',reason:'Revise'}],cells,files);
 const result=patchedSources(proposal,cells,files);
 assert.equal(result['file:paper/main.tex'],'Before\nUpdated section text\nAfter');
 assert.equal(result['cell:b'],undefined);
});
test('removing a redundant cell does not mirror deletion into the retained paper',()=>{
 const source='Duplicate abstract and introduction';
 const cells=[{id:'a',type:'latex',source}];
 const files=[{path:'paper/main.tex',content:source}];
 const edit={target:'cell',id:'a',old_text:source,new_text:'',reason:'Remove redundant copy; paper retains it',remove:true};
 validateChatEdits([edit],{notebook:cells,files});
 const proposal=prepareChatEdits([edit],cells,files);
 assert.equal(proposal.edits.length,1);
 assert.deepEqual(patchedSources(proposal,cells,files),{'cell:a':''});
 assert.throws(()=>validateChatEdits([{...edit,old_text:'Duplicate abstract'}],{notebook:cells,files}),/complete/);
 assert.throws(()=>patchedSources(proposal,[{...cells[0],source:source+' new content'}],files),/changed/);
});
test('removing a duplicate passage preserves its counterpart and unrelated content',()=>{
 const cells=[{id:'a',type:'latex',source:'Duplicate paragraph'}];
 const files=[{path:'paper/main.tex',content:'Unique opening\nDuplicate paragraph'}];
 const edit={target:'file',id:'paper/main.tex',old_text:'Duplicate paragraph',new_text:'',reason:'Keep notebook copy'};
 const proposal=prepareChatEdits([edit],cells,files);
 assert.equal(proposal.edits.length,1);
 assert.equal(patchedSources(proposal,cells,files)['file:paper/main.tex'],'Unique opening\n');
});
