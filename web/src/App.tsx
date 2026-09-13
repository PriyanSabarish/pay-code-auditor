import { Component, useEffect, useRef, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { flushSync } from 'react-dom';
import { Alert, Button, Modal, Select, Transition } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowDownToLine, ArrowRight, CircleHelp, FileSpreadsheet, RotateCcw, ShieldCheck } from 'lucide-react';
import { api, ApiError, fetchAsFile, fileError, pollInterval } from './api/client';
import type { SampleBusiness } from './api/client';
import UploadCard from './components/UploadCard';
import Results from './components/Results';
import AuditLoading from './components/AuditLoading';
import Home from './components/Home';
import SampleData from './components/SampleData';
import './experience.css';

/** Switches pages. Previously wrapped in document.startViewTransition() for a crossfade,
 * but that callback was observed to be silently skipped entirely under real navigation —
 * no callback invocation, no rejection either app code could act on, just a dead click:
 * the hash changed, the page never followed. A cosmetic animation API isn't worth that
 * risk, so this just applies the update directly; the workspace's own Transition
 * components already provide a fade for the sections that need one. */
function transitionPage(update:()=>void) {
  flushSync(update);
}

/** Expands the actual preview into a page-sized surface, then reveals the workspace. */
async function expandPreview(update:()=>void) {
  const preview=document.querySelector<HTMLElement>('.preview-document');
  if(!preview||window.matchMedia('(prefers-reduced-motion: reduce)').matches){update();return;}
  const bounds=preview.getBoundingClientRect();
  const overlay=document.createElement('div');
  overlay.className='workspace-expansion';
  overlay.setAttribute('aria-hidden','true');
  const snapshot=preview.cloneNode(true) as HTMLElement;
  snapshot.removeAttribute('id');
  snapshot.classList.add('expansion-preview');
  overlay.append(snapshot);
  Object.assign(overlay.style,{left:`${bounds.left}px`,top:`${bounds.top}px`,width:`${bounds.width}px`,height:`${bounds.height}px`});
  snapshot.style.width=`${bounds.width}px`;
  document.body.append(overlay);
  document.documentElement.classList.add('workspace-expanding');
  let navigated=false;
  const animations: Animation[]=[];
  try {
    const headerBottom=document.querySelector('.app-bar')?.getBoundingClientRect().bottom??0;
    // Soften the card content during expansion before crossfading to the workspace.
    const contentFade=snapshot.animate([{opacity:1},{opacity:.18}],{
      duration:440,delay:80,easing:'cubic-bezier(.4,0,.2,1)',fill:'forwards'
    });
    animations.push(contentFade);
    const expanded={left:'0px',top:`${headerBottom}px`,width:`${document.documentElement.clientWidth}px`,height:`${Math.max(0,window.innerHeight-headerBottom)}px`,borderRadius:'0px',background:'#f5f7f6'};
    const expansion=overlay.animate([
      {borderRadius:'15px',background:'#fffefa'},
      expanded
    ],{duration:900,easing:'cubic-bezier(.4,0,.2,1)',fill:'forwards'});
    animations.push(expansion);
    await expansion.finished;
    update();
    navigated=true;
    const workspace=document.querySelector<HTMLElement>('.audit-stage:not([hidden])');
    const timing: KeyframeAnimationOptions={duration:680,easing:'cubic-bezier(.4,0,.2,1)',fill:'both'};
    const incoming=workspace?.animate([{opacity:0},{opacity:1}],timing);
    incoming?.pause();
    if(incoming)animations.push(incoming);
    await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));
    Object.assign(overlay.style,expanded,{background:'transparent',boxShadow:'none',borderColor:'transparent'});
    expansion.cancel();
    snapshot.style.background='transparent';
    const outgoing=overlay.animate([{opacity:1},{opacity:0}],timing);
    animations.push(outgoing);
    incoming?.play();
    await Promise.all([outgoing.finished,incoming?.finished]);
  } finally {
    animations.forEach(animation=>animation.cancel());
    overlay.remove();
    document.documentElement.classList.remove('workspace-expanding');
    if(!navigated)update();
  }
}

class ErrorBoundary extends Component<{children:ReactNode},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidCatch(_error:Error,_info:ErrorInfo){/* Do not log payroll payloads. */}
  render(){return this.state.failed?<main className="page-shell"><h1>We couldn't display this workspace.</h1><p>Reload the page to try again.</p><Button onClick={()=>location.reload()}>Reload workspace</Button></main>:this.props.children;}
}

/** Coordinates the initial upload workspace and its connection state. */
function Workspace() {
  const pageForHash=()=>{
    if(location.hash==='#workspace'||location.hash==='#results'||new URLSearchParams(location.search).has('audit'))return 'workspace';
    if(location.hash==='#samples')return 'samples';
    return 'home';
  };
  const [page,setPage]=useState(pageForHash);
  useEffect(()=>{
    const syncPage=()=>transitionPage(()=>setPage(pageForHash()));
    window.addEventListener('hashchange',syncPage);
    return ()=>window.removeEventListener('hashchange',syncPage);
  },[]);
  const openingWorkspace=useRef(false);
  const openWorkspace=()=>{
    if(openingWorkspace.current)return;
    openingWorkspace.current=true;
    void expandPreview(()=>{
      const url=new URL(location.href);url.hash='workspace';history.pushState(null,'',url);
      flushSync(()=>setPage('workspace'));
      window.scrollTo({top:0,behavior:'instant'});
    }).catch(()=>{/* A cancelled animation still opens the workspace. */}).finally(()=>{openingWorkspace.current=false;});
  };
  const [paycodes,setPaycodes]=useState<File|null>(null);
  const [payruns,setPayruns]=useState<File|null>(null);
  const [awardId,setAwardId]=useState<string|null>(null);
  const [auditId,setAuditId]=useState<string|null>(()=>new URLSearchParams(location.search).get('audit'));
  const [resetOpen,setResetOpen]=useState(false);
  const [uploadVersion,setUploadVersion]=useState(0);
  const awards=useQuery({queryKey:['awards'],queryFn:({signal})=>api.awards(signal),staleTime:60_000});
  const samples=useQuery({queryKey:['samples'],queryFn:({signal})=>api.samples(signal),staleTime:60_000});
  const [samplingId,setSamplingId]=useState<string|null>(null);
  const [sampleError,setSampleError]=useState<string|null>(null);
  const job=useQuery({
    queryKey:['audit',auditId],
    queryFn:({signal})=>api.job(auditId!,signal),
    enabled:!!auditId,
    refetchInterval:query=>pollInterval(query.state.data?.status),
    refetchIntervalInBackground:true,
    retry:(count,error)=>!(error instanceof ApiError&&error.status===404)&&count<2,
  });
  const create=useMutation({mutationFn:api.create,onSuccess:data=>{
    setAuditId(data.audit_id);
    const url=new URL(location.href);url.searchParams.set('audit',data.audit_id);history.replaceState(null,'',url);
  }});
  const busy=create.isPending||!!auditId;
  const activeAwardId=awardId??job.data?.award_id;
  const businessLabel=awards.data?.find(award=>award.id===activeAwardId)?.name??'A closer look is underway.';
  const fields=create.error instanceof ApiError?create.error.fields:{};
  const codesError=fileError(paycodes)||fields.paycodes;
  const runsError=fileError(payruns)||fields.payruns;
  const ready=!!paycodes&&!!payruns&&!!awardId&&!codesError&&!runsError&&!busy;
  const activeStep=job.data?.status==='complete'?2:auditId?1:0;
  const runLabel=job.data?.status==='complete'?'Review ready':job.data?.status==='failed'?'Review interrupted':auditId?'Review in progress':'Run audit';
  const reviewing=page==='workspace'&&!!job.data;

  useEffect(()=>{
    document.documentElement.classList.toggle('audit-review-view',reviewing);
    document.body.classList.toggle('audit-review-view',reviewing);
    return ()=>{
      document.documentElement.classList.remove('audit-review-view');
      document.body.classList.remove('audit-review-view');
    };
  },[reviewing]);

  /** Loads a bundled sample business's CSVs as if the reviewer had picked them
   * themselves, then jumps to the workspace ready to run. */
  const useSample=async(business:SampleBusiness)=>{
    setSamplingId(business.id);setSampleError(null);
    try {
      const [codesFile,runsFile]=await Promise.all([
        fetchAsFile(api.samplePaycodesUrl(business.id),`${business.id}-paycodes.csv`),
        fetchAsFile(api.samplePayrunsUrl(business.id),`${business.id}-payruns.csv`),
      ]);
      setPaycodes(codesFile);setPayruns(runsFile);setAwardId(business.award_id);
      create.reset();setUploadVersion(value=>value+1);
      const url=new URL(location.href);url.hash='workspace';history.pushState(null,'',url);
      transitionPage(()=>setPage('workspace'));
    } catch (error) {
      setSampleError(error instanceof ApiError?error.message:'Could not load that sample. Check the API connection and try again.');
    } finally {
      setSamplingId(null);
    }
  };

  /** Clears the current files and returns the form to its initial state. */
  const reset=()=>{
    setAuditId(null);setPaycodes(null);setPayruns(null);setAwardId(null);
    create.reset();setUploadVersion(value=>value+1);setResetOpen(false);
    const url=new URL(location.href);url.searchParams.delete('audit');history.replaceState(null,'',url);
  };

  return <>
    <header className="app-bar">
      <a className="app-brand" href="#home" aria-label="Pay Code Auditor home"><span className="brand-mark"><ShieldCheck size={36}/></span><strong>Pay Code Auditor</strong></a>
      <nav aria-label="Primary navigation">
        <a className={page==='home'?'active':''} aria-current={page==='home'?'page':undefined} href="#home">Home</a>
        <a className={page==='workspace'?'active':''} aria-current={page==='workspace'?'page':undefined} href="#workspace">Workspace</a>
        <a className={page==='samples'?'active':''} aria-current={page==='samples'?'page':undefined} href="#samples">Sample data</a>
      </nav>
      <div className="app-bar-actions"><div className="connection"><span className={`status-dot ${awards.isSuccess?'done':''}`}/><span>{awards.isPending?'Connecting':awards.error?'Service unavailable':'Connected'}<small>{awards.isSuccess?'Audit service ready':'Check the API service'}</small></span></div>{job.data?.status==='complete'&&<a download className="header-export" href={api.reportUrl(job.data.audit_id)}><ArrowDownToLine size={16}/>Export report</a>}</div>
    </header>
    {page==='home'&&<Home onStart={openWorkspace}/>}
    {page==='samples'&&<SampleData onUseSample={useSample}/>}
    <main hidden={page!=='workspace'} className={`page-shell audit-stage ${job.data?'audit-shell':'minimal-shell'}`}>
    <Transition mounted={!job.data&&!create.isPending&&(!auditId||!!job.error)} transition="fade-up" duration={280} exitDuration={160}>
    {styles=><section style={styles} id="workspace" className="workspace-section stage-view" aria-labelledby="workspace-title">
      <div className="section-heading">
        <div><div className="eyebrow">01 / YOUR WORKSPACE</div><h1 id="workspace-title">Let's look at the details.</h1></div>
        <div className="connection"><span className={`status-dot ${awards.isSuccess?'done':''}`}/>{awards.isPending?'Connecting to service':awards.error?'Service unavailable':'Audit service connected'}</div>
      </div>
      <div className="workspace-grid">
        <div className="workspace-panel">
          <ol className="stepper" aria-label="Review progress">{['Prepare','Investigate','Review'].map((name,index)=><li key={name} className={activeStep===index?'active':''} aria-current={activeStep===index?'step':undefined}><span>{index+1}</span>{name}</li>)}</ol>
          <div className="form-heading"><h2>Start a new review</h2><p>Choose the award context and add your two payroll exports.</p></div>
          {awards.error&&<Alert color="red" title="The audit service is unavailable" mb="md">{awards.error.message}<Button size="xs" mt="xs" variant="outline" onClick={()=>void awards.refetch()}>Retry connection</Button></Alert>}
          {sampleError&&<Alert color="red" mb="md" title="Couldn't load that sample" withCloseButton onClose={()=>setSampleError(null)}>{sampleError}</Alert>}
          {!!samples.data?.length&&<div className="sample-quickpick" aria-label="Or start from a sample business">
            <span className="sample-quickpick-label"><FileSpreadsheet size={14}/>No files yet? Try a sample:</span>
            <div className="sample-quickpick-chips">
              {samples.data.map(business=><button key={business.id} type="button" className="sample-chip" disabled={busy||samplingId!==null} onClick={()=>void useSample(business)}>
                {samplingId===business.id?'Loading…':business.name}
              </button>)}
            </div>
          </div>}
          <form onSubmit={event=>{event.preventDefault();if(ready)create.mutate({paycodes:paycodes!,payruns:payruns!,award_id:awardId!});}}>
            <Select label="Award context" placeholder={awards.isPending?'Loading supported awards…':'Select an award'} data={(awards.data??[]).map(award=>({value:award.id,label:award.name}))} value={awardId} onChange={value=>{setAwardId(value);create.reset();}} disabled={busy||!awards.data?.length} error={fields.award_id} required allowDeselect={false}/>
            <UploadCard key={`codes-${uploadVersion}`} label="01 / Pay codes" description="Payment categories and current settings" file={paycodes} disabled={busy} error={codesError} onChange={file=>{setPaycodes(file);create.reset();}}/>
            <UploadCard key={`runs-${uploadVersion}`} label="02 / Pay runs" description="Payment history for the review period" file={payruns} disabled={busy} error={runsError} onChange={file=>{setPayruns(file);create.reset();}}/>
            {create.error&&<Alert color="red" mb="md" title="We couldn't start this audit">{create.error.message}</Alert>}
            {job.error&&<Alert color="red" mb="md" title="The review could not be refreshed">{job.error.message}</Alert>}
            <Button fullWidth size="md" type="submit" loading={create.isPending} disabled={!ready} rightSection={<ArrowRight size={16}/>}>{runLabel}</Button>
            <p className="fine-print"><CircleHelp size={13}/>Your files are sent to the connected audit service for review.</p>
          </form>
          {auditId&&<Button variant="subtle" fullWidth mt="xs" leftSection={<RotateCcw size={14}/>} onClick={()=>setResetOpen(true)}>Start a different review</Button>}
        </div>
      </div>
    </section>}</Transition>
    <Transition mounted={!job.data&&!job.error&&(create.isPending||!!auditId)} transition="fade-up" duration={380} enterDelay={160} exitDuration={160}>
      {styles=><div style={styles} className="stage-view"><AuditLoading uploading/></div>}
    </Transition>
    {job.data&&<div className="stage-view audit-arrival"><Results job={job.data} businessLabel={businessLabel} onNewReview={()=>setResetOpen(true)}/></div>}
    <Modal opened={resetOpen} onClose={()=>setResetOpen(false)} title="Start a new review?" centered size="sm" radius="lg" classNames={{root:'reset-modal-root',overlay:'reset-modal-overlay',inner:'reset-modal-inner',content:'reset-modal',body:'reset-modal-body'}} overlayProps={{backgroundOpacity:.62}}><p>This clears the current files and status from this screen.</p><div className="reset-actions"><Button variant="outline" onClick={()=>setResetOpen(false)}>Keep this review</Button><Button onClick={reset}>Start new review</Button></div></Modal>
    </main>
  </>;
}

/** Mounts the initial workspace inside an application-level error boundary. */
export default function App(){return <ErrorBoundary><Workspace/></ErrorBoundary>;}
