import { useId, useRef, useState } from 'react';
import { FileCheck2, Upload, X } from 'lucide-react';

type Props = {label:string;description:string;file:File|null;onChange:(file:File|null)=>void;error?:string;disabled:boolean};
/** Renders an accessible CSV picker with drag-and-drop support. */
export default function UploadCard({label,description,file,onChange,error,disabled}:Props) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [over,setOver] = useState(false);
  return <div className="upload-field">
    <label className="field-label" htmlFor={id}>{label}</label>
    <input ref={input} id={id} type="file" accept=".csv,text/csv" disabled={disabled} aria-describedby={`${id}-help`} aria-invalid={!!error} className="sr-only" onChange={event=>onChange(event.target.files?.[0]??null)}/>
    <div className={`file-zone ${over?'dragging':''} ${file?'has-file':''} ${error?'invalid':''}`} onDragOver={event=>{event.preventDefault();if(!disabled)setOver(true);}} onDragLeave={()=>setOver(false)} onDrop={event=>{event.preventDefault();setOver(false);if(!disabled)onChange(event.dataTransfer.files[0]??null);}}>
      {file?<FileCheck2 size={27} strokeWidth={1.4}/>:<Upload size={27} strokeWidth={1.4}/>}
      <div className="file-copy"><span>{file?file.name:'Drop your CSV here'}</span><small>{file?`${(file.size/1024).toFixed(1)} KB · ready to upload`:description}</small></div>
      {file?<button type="button" className="icon-button" aria-label={`Remove ${label}`} disabled={disabled} onClick={()=>{onChange(null);if(input.current)input.current.value='';}}><X size={17}/></button>:<button type="button" className="browse-button" disabled={disabled} onClick={()=>input.current?.click()}>Browse files</button>}
    </div>
    <p id={`${id}-help`} className={error?'field-error':'upload-hint'}>{error??'CSV UTF-8 · Up to 5 MB'}</p>
  </div>;
}
