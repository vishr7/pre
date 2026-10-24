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
