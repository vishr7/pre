import type {Cell,ProjectFile} from './api';
export type UploadedFigure={path:string;data:string};
// Uploaded figures (kept in memory until refresh) are included with notebook plots at their own paths.
export function figureAssets(cells:Cell[],files:ProjectFile[],uploads:UploadedFigure[]=[]){
 const assets:{path:string;data:string}[]=[...uploads];
 function collect(images:unknown,prefix:string){if(!Array.isArray(images))return;for(const [i,image] of images.entries()){
 if(typeof image!=='string'||!image.startsWith('data:image/png;base64,'))continue;
 const data=image.slice(22);if(data.length>2000000)continue;
 assets.push({path:`figures/${prefix}-${i+1}.png`,data});
 }}
 for(const cell of cells)collect(cell.images,`cell-${cell.id.replace(/[^a-zA-Z0-9_-]/g,'_')}`);
 for(const file of files.filter(f=>f.path.startsWith('replication/')&&f.path.endsWith('.results.json'))){try{const run=JSON.parse(file.content);collect(run.images,file.path.split('/').pop()!.replace('.results.json',''));}catch{}}
 return assets.slice(0,40);
}
export function compileErrorSummary(message:string){
 const missing=/Unable to load picture or PDF file ['"]([^'"]+)['"]/.exec(message)||/File [`'"]([^`'"]+)['"] not found/.exec(message);
 if(missing)return `Could not compile: missing file “${missing[1]}”. Use an available project figure or upload the file. Your edits were not applied. See Logs for details.`;
 const line=message.split('\n').find(line=>/^error:|^!/.test(line));
 return `${(line||message).slice(0,220)}${message.length>220?' — see Logs for details.':''}`;
}
