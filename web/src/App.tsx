import { Component, useRef, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { Alert, Button, Modal, Select } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowRight, ArrowUpRight, BookOpen, Check, CircleHelp, FileCheck2, RotateCcw } from 'lucide-react';
import { api, ApiError, fileError, pollInterval } from './api/client';
import UploadCard from './components/UploadCard';
import Results from './components/Results';

class ErrorBoundary extends Component<{children:ReactNode},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidCatch(_error:Error,_info:ErrorInfo){/* Do not log payroll payloads. */}
  render(){return this.state.failed?<main className="page-shell"><h1>We couldn't display this review.</h1><p>The API response may not match the frontend contract. Reload to start again.</p><Button onClick={()=>location.reload()}>Reload workspace</Button></main>:this.props.children;}
}

function Workspace() {
  const [paycodes,setPaycodes]=useState<File|null>(null);
  const [payruns,setPayruns]=useState<File|null>(null);
  const [awardId,setAwardId]=useState<string|null>(null);
  const [auditId,setAuditId]=useState<string|null>(null);
  const [resetOpen,setResetOpen]=useState(false);
  const [uploadVersion,setUploadVersion]=useState(0);
  const resultsAnchor=useRef<HTMLDivElement>(null);
  const awards=useQuery({queryKey:['awards'],queryFn:({signal})=>api.awards(signal),staleTime:60_000});
  const job=useQuery({queryKey:['audit',auditId],queryFn:({signal})=>api.job(auditId!,signal),enabled:!!auditId,
    refetchInterval:query=>pollInterval(query.state.data?.status),
    retry:(count,error)=>!(error instanceof ApiError&&error.status===404)&&count<2,
  });
  const create=useMutation({mutationFn:api.create,onSuccess:data=>{setAuditId(data.audit_id);requestAnimationFrame(()=>resultsAnchor.current?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'}));}});
  const preview=awards.data?.some(award=>award.preview)??false;
  const busy=create.isPending||!!auditId;
  const fields=create.error instanceof ApiError?create.error.fields:{};
  const codesError=fileError(paycodes)||fields.paycodes;
  const runsError=fileError(payruns)||fields.payruns;
  const ready=!!paycodes&&!!payruns&&!!awardId&&!codesError&&!runsError&&!busy;
  const runLabel=job.data?.status==='complete'?'Review ready':job.data?.status==='failed'?'Review interrupted':auditId?'Review in progress':preview?'Run sample audit':'Run audit';
  const reset=()=>{setAuditId(null);setPaycodes(null);setPayruns(null);setAwardId(null);create.reset();setUploadVersion(v=>v+1);setResetOpen(false);document.getElementById('workspace')?.scrollIntoView({block:'start'});};
  const sample=()=>{
    const award=awards.data?.find(a=>a.preview);
    if(!award)return;
    const codes=new File(['code,description\nDEMO_01,Fictional code\nDEMO_02,Illustrative code\n'],'sample-paycodes.csv',{type:'text/csv'});
    const runs=new File(['code,amount\nDEMO_01,100\nDEMO_02,50\n'],'sample-payruns.csv',{type:'text/csv'});
    setPaycodes(codes);setPayruns(runs);setAwardId(award.id);create.mutate({paycodes:codes,payruns:runs,award_id:award.id});
  };
  return <div className="page-shell">
    <a className="skip-link" href="#workspace">Skip to workspace</a>
    <header className="masthead" id="top"><a className="brand" href="#top" aria-label="Pay Code Auditor home"><span className="brand-mark">pc.</span><span><strong>Pay Code Auditor</strong><small>THE BOOKKEEPER'S COMPANION</small></span></a>
    <nav aria-label="Main navigation"><a href="#workspace">Workspace</a><a href="#process">The process</a><span className="edition">HACKATHON EDITION / 02</span></nav></header>
    <main>
      <section className="hero" aria-labelledby="hero-title"><div className="hero-content"><div className="eyebrow"><span className="tiny-star" aria-hidden="true">✳</span> A FRESH LOOK AT THE FINE PRINT.</div><h1 id="hero-title">Old-school care.<br/><em>New-school clarity.</em></h1><p>Make sense of your pay codes. Follow the evidence, ask the right questions, and give every payroll decision a second look.</p><div className="hero-actions"><a className="button-primary" href="#workspace">Open your workspace <ArrowUpRight size={17}/></a><a className="underlined-link" href="#process">See how it works <ArrowRight size={14}/></a></div><div className="hero-note"><span className="mini-rule"/>Made for bookkeepers. Built for the details.</div></div>
      <figure className="hero-art"><img src="/ledger.svg" width="540" height="410" alt="A vintage payroll ledger and magnifying glass, marked sample only"/><figcaption><span>FIG. 01 — A CLOSER LOOK</span><span>EVERY DETAIL MATTERS.</span></figcaption></figure></section>
      <div className="ribbon"><span><b>01 /</b> BRING YOUR PAYROLL FILES</span><span><b>02 /</b> FOLLOW THE EVIDENCE</span><span><b>03 /</b> KEEP THE FINAL SAY</span></div>
      <section id="workspace" className="workspace-section"><div className="section-heading"><div><div className="eyebrow">01 / YOUR WORKSPACE</div><h2>Let's look at the details.</h2></div><div className="connection"><span className={`status-dot ${awards.isSuccess?'done':''}`}/>{awards.isPending?'Connecting to service':awards.error?'Service unavailable':preview?'Sample workspace connected':'Audit service connected'}</div></div>
      <div className="workspace-grid"><div className="workspace-panel"><ol className="stepper" aria-label="Review progress">{['Prepare','Investigate','Review'].map((name,index)=><li key={name} className={(job.data?.status==='complete'?2:auditId?1:0)===index?'active':''} aria-current={(job.data?.status==='complete'?2:auditId?1:0)===index?'step':undefined}><span>{index+1}</span>{name}</li>)}</ol>
        <div className="form-heading"><h3>Start a new review</h3><p>Choose the award context and add your two payroll exports.</p></div>
        {awards.error&&<Alert color="red" title="The audit service is unavailable" mb="md">{awards.error.message}<Button size="xs" mt="xs" variant="outline" onClick={()=>void awards.refetch()}>Retry connection</Button></Alert>}
        <form onSubmit={event=>{event.preventDefault();if(ready)create.mutate({paycodes:paycodes!,payruns:payruns!,award_id:awardId!});}}>
          <Select label="Award context" placeholder={awards.isPending?'Loading supported awards…':'Select an award'} data={(awards.data??[]).map(award=>({value:award.id,label:award.name}))} value={awardId} onChange={value=>{setAwardId(value);create.reset();}} disabled={busy||!awards.data?.length} error={fields.award_id} required allowDeselect={false} rightSection={<ChevronIcon/>}/>
          <UploadCard key={`codes-${uploadVersion}`} label="01 / Pay codes" description="Payment categories and current settings" file={paycodes} disabled={busy} error={codesError} onChange={file=>{setPaycodes(file);create.reset();}}/>
          <UploadCard key={`runs-${uploadVersion}`} label="02 / Pay runs" description="Payment history for the review period" file={payruns} disabled={busy} error={runsError} onChange={file=>{setPayruns(file);create.reset();}}/>
          {create.error&&<Alert color="red" mb="md" title="We couldn't start this audit">{create.error.message}</Alert>}
          <Button fullWidth size="md" type="submit" loading={create.isPending} disabled={!ready} rightSection={<ArrowRight size={16}/>}>{runLabel}</Button>
          <p className="fine-print"><CircleHelp size={13}/>{preview?'Preview service: files are checked for format, then fictional results are returned. Use sample data only.':'Your files are sent to the connected audit service for review.'}</p>
        </form>
        {auditId&&<Button variant="subtle" fullWidth mt="xs" leftSection={<RotateCcw size={14}/>} onClick={()=>setResetOpen(true)}>Start a different review</Button>}
      </div>
      <aside className="notebook"><div className="note-kicker"><BookOpen size={15}/> A NOTE FROM YOUR WORKSPACE</div><h3>Good records.<br/>Better questions.</h3><p>A pay code name is only part of the story. A useful review brings the context along with it.</p><ul><li><span>01</span><div><strong>Pay-code settings</strong><small>Your payment categories and current setup.</small></div></li><li><span>02</span><div><strong>Payment history</strong><small>The amounts and timing behind each code.</small></div></li><li><span>03</span><div><strong>Your professional judgement</strong><small>You review the evidence and make the call.</small></div></li></ul>
      <div className="sample-start"><Button variant="outline" color="dark" fullWidth onClick={sample} disabled={!preview||busy} loading={create.isPending} rightSection={<ArrowUpRight size={16}/>}>Explore a sample audit</Button><p>{preview?'No files handy? Take a look around with a fictional cafe. No API key needed.':'Sample mode is available when the preview API is connected.'}</p></div><div className="note-bottom"><Check size={14}/> THE FINAL SAY IS ALWAYS YOURS.</div></aside></div></section>
      <div ref={resultsAnchor} className="results-anchor"/>
      {auditId&&job.isPending&&<div className="loading-panel" role="status"><FileCheck2 size={28}/><h3>Opening your review…</h3><p>Waiting for the audit service to prepare the records.</p></div>}
      {auditId&&job.error&&<Alert color="red" title="The review could not be refreshed" my="xl">{job.error.message}<div className="flex gap-3 mt-3"><Button variant="outline" size="xs" onClick={()=>void job.refetch()}>Retry connection</Button><Button variant="subtle" size="xs" onClick={()=>setResetOpen(true)}>Start another review</Button></div></Alert>}
      {job.data&&auditId&&<Results key={auditId} job={job.data}/>}
      <section id="process" className="process-section"><div className="section-heading"><div><div className="eyebrow">03 / THE PROCESS</div><h2>From paperwork to perspective.</h2></div><span className="small-mono">A LITTLE STRUCTURE GOES A LONG WAY.</span></div><div className="process-grid">{[{number:'01',title:'Bring the context.',text:'Add your pay codes, payment history, and award context. Start with the records you already have.'},{number:'02',title:'Follow the evidence.',text:'Explore the investigation steps and supporting passages. Add context when the system has a question.'},{number:'03',title:'Make an informed call.',text:'Review each recommendation, record your decision, and take away a report of your findings.'}].map(item=><article key={item.number}><span className="process-number">{item.number}</span><h3>{item.title}</h3><p>{item.text}</p></article>)}</div></section>
    </main>
    <footer className="footer"><strong>Pay Code Auditor.</strong><span>MADE WITH CARE. CHECKED BY YOU.</span><a href="#top">BACK TO TOP <ArrowUpRight size={12}/></a></footer>
    <Modal opened={resetOpen} onClose={()=>setResetOpen(false)} title="Start a new review?" centered><p>This clears the current files and results from this screen. Any existing job stays on the server until it expires or the server restarts.</p><div className="flex gap-3 mt-5"><Button variant="outline" onClick={()=>setResetOpen(false)}>Keep this review</Button><Button onClick={reset}>Start new review</Button></div></Modal>
  </div>;
}
function ChevronIcon(){return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 9 6 6 6-6" stroke="currentColor" strokeWidth="1.5"/></svg>;}
export default function App(){return <ErrorBoundary><Workspace/></ErrorBoundary>;}
