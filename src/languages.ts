export const codeLanguages = [
 ['python','Python'],['javascript','JavaScript'],['typescript','TypeScript'],['java','Java'],['c','C'],['cpp','C++'],['csharp','C#'],['go','Go'],['rust','Rust'],['ruby','Ruby'],['php','PHP'],['swift','Swift'],['kotlin','Kotlin'],['r','R'],['julia','Julia'],['shell','Shell'],['sql','SQL'],['html','HTML'],['css','CSS'],['json','JSON'],['yaml','YAML'],['xml','XML'],['scala','Scala'],['lua','Lua'],['perl','Perl'],['powershell','PowerShell'],['dockerfile','Dockerfile']
] as const;
export type CodeLanguage = typeof codeLanguages[number][0];
export const canRun = (language:string) => ['python','javascript','latex','markdown'].includes(language);
export const isCode = (language:string) => !['latex','markdown'].includes(language);
