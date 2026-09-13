import { useEffect, useRef } from 'react';

type AuditLoadingProps = {
  uploading?: boolean;
  processed?: number;
  total?: number;
  step?: string | null;
  compact?: boolean;
};

/** Shows real audit progress alongside a decorative document-scanning animation. */
export default function AuditLoading({uploading=false,processed=0,total=0,step,compact=false}:AuditLoadingProps) {
  const heading=useRef<HTMLHeadingElement>(null);
  useEffect(()=>{
    if(compact)return;
    heading.current?.focus({preventScroll:true});
    window.scrollTo({top:0,behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  },[compact]);
  const count=Math.max(0,Math.min(processed,total));
  return <section className={`audit-loading ${compact?'audit-loading-compact':''}`} aria-label="Audit progress">
    <svg className="audit-illustration" viewBox="0 0 260 200" fill="none" aria-hidden="true">
      <ellipse cx="128" cy="179" rx="85" ry="9" fill="currentColor" opacity=".06"/>
      <circle cx="130" cy="95" r="80" fill="currentColor" opacity=".04"/>
      <g className="audit-paper">
        <rect x="65" y="32" width="115" height="139" rx="10" fill="#edf4f1" stroke="#c8d9d2" transform="rotate(-8 122 101)"/>
        <rect x="74" y="25" width="115" height="143" rx="10" fill="white" stroke="#c8d9d2" strokeWidth="1.5"/>
        <path d="M94 48h48M94 57h29" stroke="#79948b" strokeWidth="4" strokeLinecap="round"/>
        {[80,103,126].map((y,i)=><g key={y}><rect x="92" y={y-6} width="12" height="12" rx="3" fill="#eef5f2"/><path className={`audit-tick audit-tick-${i}`} d={`M95 ${y}l2 2 4-5`} stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/><path d={`M116 ${y}h51M116 ${y+7}h32`} stroke="#dce5e1" strokeWidth="3" strokeLinecap="round"/></g>)}
        <path className="audit-scan" d="M85 71h93" stroke="#70b4a1" strokeWidth="3" strokeLinecap="round" opacity=".5"/>
      </g>
      <g className="audit-lens">
        <path d="m169 124 26 27" stroke="#254e44" strokeWidth="13" strokeLinecap="round"/>
        <circle cx="150" cy="105" r="31" fill="#e2f1ec" fillOpacity=".8" stroke="currentColor" strokeWidth="6"/>
        <path d="M132 102a19 19 0 0 1 17-16" stroke="white" strokeWidth="4" strokeLinecap="round"/>
        <path d="m139 106 8 8 16-19" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
      </g>
    </svg>
    <div className="audit-loading-copy">
      <span className="eyebrow">{uploading?'PREPARING YOUR REVIEW':'INVESTIGATION IN PROGRESS'}</span>
      <h2 ref={heading} tabIndex={-1}>{uploading?'Opening your audit workspace':'Taking a closer look at your payroll'}</h2>
      <p role="status" aria-live="polite">{uploading?'Sending your files to the audit service…':step||'Checking pay codes and gathering supporting evidence…'}</p>
      <div className={`audit-loading-track ${!total?'indeterminate':''}`} role="progressbar" aria-label="Pay codes processed" aria-valuemin={0} aria-valuemax={total||100} aria-valuenow={total?count:undefined}><i style={total?{width:`${100*count/total}%`}:undefined}/></div>
      <span className="audit-loading-count">{total?`${count} of ${total} pay codes processed`:'Your review will appear here automatically.'}</span>
    </div>
  </section>;
}
